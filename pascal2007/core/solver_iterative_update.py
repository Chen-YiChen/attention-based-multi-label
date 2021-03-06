import tensorflow as tf
import matplotlib.pyplot as plt
import skimage.transform
import numpy as np
import time
import math
import os
import cPickle as pickle
from scipy import ndimage
from utils_pascal import *


class CaptioningSolver(object):
    def __init__(self, model, data_path, **kwargs):
        """
        Required Arguments:
            - model: Show Attend and Tell caption generating model
            - data_path:
              Contain training data; dictionary with the following keys:
                - features: Feature vectors of shape (82783, 196, 512)
                - file_names: Image file names of shape (82783, )
                - captions: Captions of shape (400000, 17)
                - image_idxs: Indices for mapping caption to image of shape (400000, )
                - word_to_idx: Mapping dictionary from word to index
            - val_data: validation data; for print out BLEU scores for each epoch.
        Optional Arguments:
            - n_epochs: The number of epochs to run for training.
            - batch_size: Mini batch size.
            - update_rule: A string giving the name of an update rule
            - learning_rate: Learning rate; default value is 0.01.
            - print_every: Integer; training losses will be printed every print_every iterations.
            - save_every: Integer; model variables will be saved every save_every epoch.
            - pretrained_model: String; pretrained model path
            - model_path: String; model path for saving
            - test_model: String; model path for test
        """

        self.model = model
        self.data_path = data_path
        self.data = None
        self.n_epochs = kwargs.pop('n_epochs', 10)
        self.batch_size = kwargs.pop('batch_size', 100)
        self.update_rule = kwargs.pop('update_rule', 'adam')
        self.learning_rate = kwargs.pop('learning_rate', 0.01)
        self.print_bleu = kwargs.pop('print_bleu', False)
        self.print_every = kwargs.pop('print_every', 100)
        self.save_every = kwargs.pop('save_every', 1)
        self.log_path = kwargs.pop('log_path', './log/')
        self.model_path = kwargs.pop('model_path', './model/')
        self.pretrained_model = kwargs.pop('pretrained_model', None)
        self.test_model = kwargs.pop('test_model', './model/lstm/model-1')
        self.V = kwargs.pop('V', 23)
        self.n_time_step = kwargs.pop('n_time_step', 8)

        # set an optimizer by update rule
        if self.update_rule == 'adam':
            self.optimizer = tf.train.AdamOptimizer
        elif self.update_rule == 'momentum':
            self.optimizer = tf.train.MomentumOptimizer
        elif self.update_rule == 'rmsprop':
            self.optimizer = tf.train.RMSPropOptimizer

        if not os.path.exists(self.model_path):
            os.makedirs(self.model_path)
        if not os.path.exists(self.log_path):
            os.makedirs(self.log_path)


    def train(self):

        # build graphs for training model and sampling captions
        loss = self.model.build_model()
        tf.get_variable_scope().reuse_variables()
        # _, _, generated_captions = self.model.build_sampler(max_len=15)

        # train op
        with tf.name_scope('optimizer'):
            optimizer = self.optimizer(learning_rate=self.learning_rate)
            grads = tf.gradients(loss, tf.trainable_variables())
            grads_and_vars = list(zip(grads, tf.trainable_variables()))
            train_op = optimizer.apply_gradients(grads_and_vars=grads_and_vars)

        # summary op
        tf.scalar_summary('batch_loss', loss)
        for var in tf.trainable_variables():
            tf.histogram_summary(var.op.name, var)
        for grad, var in grads_and_vars:
            tf.histogram_summary(var.op.name+'/gradient', grad)

        summary_op = tf.merge_all_summaries()

        print "The number of epoch: %d" %self.n_epochs
        print "Batch size: %d" %self.batch_size

        config = tf.ConfigProto(allow_soft_placement = True)
        config.gpu_options.per_process_gpu_memory_fraction=0.3
        # config.gpu_options.allow_growth = True
        with tf.Session(config=config) as sess:
            tf.initialize_all_variables().run()
            summary_writer = tf.train.SummaryWriter(self.log_path, graph=tf.get_default_graph())
            saver = tf.train.Saver(max_to_keep=100)

            if self.pretrained_model is not None:
                print "Start training with pretrained Model.."
                saver.restore(sess, self.pretrained_model)
            prev_loss = -1
            curr_loss = 0
            start_t = time.time()
            for e in range(self.n_epochs):
                print '##################'
                print 'epoch ' + str(e+1)
                print '##################'
                self.data = load_pascal_data(data_path=self.data_path, split='train', load_init_pred=True)
                n_examples = self.data['captions'].shape[0]
                n_iters_per_part = int(np.ceil(float(n_examples)/self.batch_size))
                features = self.data['features']
                init_pred = self.data['init_pred']
                captions = self.data['captions']

                # groundtruth, logits_mask and end_time
                groundtruth = np.zeros((n_examples, self.V), dtype=np.float32)
                for n, caption in enumerate(captions):
                    for index in caption:
                        if index > 2:
                            groundtruth[n][index] = 1.0

                label_num = np.sum(groundtruth, axis=1)

                image_idxs = self.data['image_idxs']
                print "Data size: %d" %n_examples
                print "Iterations per part: %d" %n_iters_per_part

                rand_idxs = np.random.permutation(n_examples)
                captions = captions[rand_idxs]
                groundtruth = groundtruth[rand_idxs]
                image_idxs = image_idxs[rand_idxs]

                for i in range(n_iters_per_part):
                    captions_batch = captions[i*self.batch_size:(i+1)*self.batch_size]
                    groundtruth_batch = groundtruth[i*self.batch_size:(i+1)*self.batch_size]
                    image_idxs_batch = image_idxs[i*self.batch_size:(i+1)*self.batch_size]
                    features_batch = features[image_idxs_batch]
                    init_pred_batch = init_pred[image_idxs_batch]
                    self.model.set_batch_size(len(captions_batch))
                    # set end_time
                    feed_dict = {self.model.features: features_batch, 
                                    self.model.captions: captions_batch, 
                                    self.model.init_pred: init_pred_batch, 
                                    self.model.groundtruth: groundtruth_batch} 
                    _, l = sess.run([train_op, loss], feed_dict)
                    curr_loss += l
                    # write summary for tensorboard visualization
                    if i % 10 == 0:
                        summary = sess.run(summary_op, feed_dict)
                        summary_writer.add_summary(summary, e*n_iters_per_part + i)
                    '''
                    if (i+1) % self.print_every == 0:
                        # print "\nTrain loss at epoch %d & iteration %d (mini-batch): %.5f" %(e+1, i+1, l)
                        ground_truths = captions[image_idxs == image_idxs_batch[0]]
                        decoded = decode_captions(ground_truths, self.model.idx_to_word)
                        for j, gt in enumerate(decoded):
                            print "Ground truth %d: %s" %(j+1, gt)
                        gen_caps = sess.run(generated_captions, feed_dict)
                        decoded = decode_captions(gen_caps, self.model.idx_to_word)
                        print "Generated caption: %s\n" %decoded[0]
                    '''
                print "Previous epoch loss: " , prev_loss
                print "Current epoch loss: " , curr_loss
                print "Elapsed time: ", time.time() - start_t
                prev_loss = curr_loss
                curr_loss = 0
                # save model's parameters
                if (e+1) % self.save_every == 0:
                    saver.save(sess, os.path.join(self.model_path, 'pascal_y'), global_step=e+1)
                    print "pascal_y-%s saved." %(e+1)

    def softmax(self, array):
        total = 0.0
        for i in range(len(array)):
            array[i] = np.exp(array[i])
            total += array[i]
        return array/total

    def sigmoid(self, array):
        array = array[3:]
        for i in range(len(array)):
            array[i] = 1/(1 + np.exp(-array[i]))
        return array

    def evaluate_map(self, predict, split,resultFile):
        predict = np.transpose(predict, (1, 0))
        loaded_reference = load_pickle('/home/jason6582/sfyc/attention-tensorflow/pascal2007/pascaldata/%s/%s.references.pkl'\
                                        % (split, split))
        reference = np.zeros(predict.shape)
        for key, value in loaded_reference.iteritems():
            answer = []
            for label in value[0]:
                reference[label-3][key] = 1
        g = open(resultFile, 'w')
        word_to_idx = load_word_to_idx(data_path='/home/jason6582/sfyc/attention-tensorflow/pascal2007/pascaldata',\
                      split='train')
        idx_to_word = {i:w for w, i in word_to_idx.iteritems()}
        # feature = np.concatenate((feature, sum_feature))
        label_list = ['aeroplane', 'bicycle', 'bird', 'boat', 'bottle', 'bus', 'car', 'cat', \
                      'chair', 'cow', 'dining_table', 'dog', 'horse', 'motorbike', 'person', \
                      'plant', 'sheep', 'sofa', 'train', 'tv']
        all_map = []
        for i, label in enumerate(label_list):
            map_dic = {}
            for j, instance in enumerate(reference[i]):
                map_dic[predict[i][j]] = reference[i][j]
            map_list = []
            total_count = 0.0
            correct_count = 0.0
            for key in reversed(sorted(map_dic.iterkeys())):
                total_count += 1.0
                if map_dic[key] == 1:
                    correct_count += 1.0
                    map_list.append(correct_count/total_count)
            l = len(map_list)
            for i in range(l-1):
                if map_list[l-i-1] > map_list[l-i-2]:
                    map_list[l-i-2] = map_list[l-i-1]
            all_map.append(sum(map_list)/len(map_list))
            g.write(label + '\nmAP: ' + str(sum(map_list)/len(map_list)) + '\n\n')
        g.write('Average: ' + str(sum(all_map)/len(all_map)))

    def evaluate(self, feature, thres, split, resultFile):
        loaded_reference = load_pickle('/home/jason6582/sfyc/attention-tensorflow/pascal2007/pascaldata/%s/%s.references.pkl'\
                                        % (split,split))
        reference = []
        for key, value in loaded_reference.iteritems():
            answer = []
            for label in value[0]:
                answer.append(label-3)
            reference.append(answer)
        g = open(resultFile, 'w')

        word_to_idx = load_word_to_idx(data_path='/home/jason6582/sfyc/attention-tensorflow/pascal2007/pascaldata',\
                      split='train')
        idx_to_word = {i:w for w, i in word_to_idx.iteritems()}
        # sum_feature = np.reshape(sum(feature)/5, (1, -1, 20))
        # feature = np.concatenate((feature, sum_feature))

        for iter_num, iteration in enumerate(feature):
            refsNum = 0
            cansNum = 0
            correctNum = 0
            classwise_num = np.zeros((3,20))
            num = 0
            for i in range(len(iteration)):
                cans = []
                for j, label in enumerate(iteration[i]):
                    if label > thres:
                        cans.append(j)
                if len(cans) == 0:
                    cans.append(int(np.argmax(iteration[i])))
                cansNum += len(cans)
                refs = reference[i]
                refsNum += len(refs)
                refsDict = {}
                correct = 0
                for c in cans:
                    refsDict[c] = 0  # follow idx of word_to_idx (keep 0, 1, 2)
                    classwise_num[0][c] += 1.0 # idx start from 0 for convenience
                for r in refs:
                    refsDict[r] = 1
                    classwise_num[1][r] += 1.0
                for c in cans:
                    if refsDict[c] == 1:
                        correct += 1
                        classwise_num[2][c] += 1.0
                correctNum += correct
            recall = float(correctNum)/float(refsNum)
            precision = float(correctNum)/float(cansNum)
            o_f1 = 2.0/((1.0/recall) + (1.0/precision))
            for i in range(len(classwise_num[0])):
                if classwise_num[0][i] == 0.0:
                    classwise_num[0][i] = 1.0
            for i in range(len(classwise_num[1])):
                if classwise_num[1][i] == 0.0:
                    classwise_num[1][i] = 1.0
            recall_arr = classwise_num[2] / classwise_num[1]
            precision_arr = classwise_num[2] / classwise_num[0]
            # precision_arr = np.divide(classwise_num[2], classwise_num[0])
            c_recall = np.mean(recall_arr)
            c_precision = np.mean(precision_arr)
            c_f1 = 2.0/((1.0/c_recall) + (1.0/c_precision))
            g.write('Iteration: ' + str(iter_num+1) + '\n')
            g.write('O-R: ' + str(recall) + '\n')
            g.write('O-P: ' + str(precision) + '\n')
            g.write('O-F1: ' + str(o_f1) + '\n')
            g.write('C-R: ' + str(c_recall) + '\n')
            g.write('C-P: ' + str(c_precision) + '\n')
            g.write('C-F1: ' + str(c_f1) + '\n')
            g.write('Average: ' + str((c_f1+o_f1)/2) + '\n\n')

    def test(self, data, split='train', attention_visualization=True, save_sampled_captions=True,\
             filename='', thres=0.0):
        '''
        Args:
            - data: dictionary with the following keys:
            - features: Feature vectors of shape (5000, 196, 512)
            - file_names: Image file names of shape (5000, )
            - captions: Captions of shape (24210, 17)
            - image_idxs: Indices for mapping caption to image of shape (24210, )
            - features_to_captions: Mapping feature to captions (5000, 4~5)
            - split: 'train', 'val' or 'test'
            - attention_visualization: If True, visualize attention weights with images for each sampled word. (ipthon notebook)
            - save_sampled_captions: If True, save sampled captions to pkl file for computing BLEU scores.
        '''

        features = data['features']
        init_pred = data['init_pred']
        # build a graph to sample captions
        config = tf.ConfigProto(allow_soft_placement=True)
        config.gpu_options.allow_growth = True
        probabilities_start, c_start, h_start, alpha_start, x_start = self.model.init_sampler()
        probabilities, c, h, alpha, x = self.model.word_sampler()
        with tf.Session(config=config) as sess:
            saver = tf.train.Saver()
            saver.restore(sess, self.test_model)
            MAX_LEN = 3
            num_iter = features.shape[0]
            start_t = time.time()
            for thres_iter in range(1):
                all_prediction = []
                all_alphas = []
                for i in range(num_iter):
                    if i % 50 == 0:
                        print "Iteration: ", i
                    features_batch = features[i:i+1]
                    init_pred_batch = init_pred[i:i+1]
                    x_run = None
                    prediction = []
                    for t in range(MAX_LEN): # time step
                        dic = {}
                        if t == 0:
                            path = []
                            alphas = []
                            feed_dict = { self.model.features: features_batch, 
                                            self.model.init_pred: init_pred_batch}
                            probsNumpy, c_run, h_run, alpha_run, x_run = \
                            sess.run([probabilities_start, c_start, h_start, alpha_start, \
                                        x_start], feed_dict)
                            probsNumpy = probsNumpy.reshape(self.V)
                        else:
                            path, c_run, h_run, alphas, samp_run, x_run = paths_info[0]
                            feed_dict = { self.model.features: features_batch,
                                            self.model.init_pred: init_pred_batch,
                                            self.model.c: c_run,
                                            self.model.h: h_run,
                                            self.model.samp: samp_run,
                                            self.model.prev_pred: x_run }
                            probsNumpy, c_run, h_run, alpha_run, x_run = \
                            sess.run([probabilities, c, h, alpha, x], feed_dict)
                            probsNumpy = probsNumpy.reshape(self.V)
                        alphas.append(alpha_run)
                        probsNumpy = self.sigmoid(probsNumpy)
                        probs = []
                        for p in probsNumpy:
                            probs.append(p)
                        prediction.append(probs)
                        for k in range(len(probs)):
                            idx = probs[k]
                            p = path[:]
                            p.append(k)
                            samp_run = np.array([k+3])
                            dic[idx] = (p, c_run , h_run, alphas, samp_run, x_run) # p is a path(list), and h is p's current hidden state
                        newPaths_info = []
                        for key in reversed(sorted(dic.iterkeys())):
                            newPaths_info.append(dic[key][:])
                            break
                        paths_info = newPaths_info
                        # print pathProbs
                    all_prediction.append(prediction)
                    alphas = paths_info[0][3]
                    alpha_list = np.transpose(alphas, (1, 0, 2))     # (N, T, L)
                    all_alphas.append(alpha_list)
                save_file = self.test_model[11:]
                all_prediction = np.array(all_prediction)
                all_prediction = np.transpose(all_prediction, (1, 0, 2))
                self.evaluate(all_prediction, 0.3, split, 'pascaldata/%s/'%split + save_file + '.txt')
                self.evaluate_map(all_prediction[0], split, 'pascaldata/%s/'%split + save_file + '_map.txt')
                save_pickle(all_prediction[0], './pascaldata/%s/%s_pred.pkl' % (split, filename))
                print save_file, "saved."
                print "Time cost: ", time.time()- start_t

            image_file_name = 'visualization/'
            if attention_visualization:
                # plt.rcParams['figure.figsize'] = (8.0, 6.0)
                # plt.rcParams['image.interpolation'] = 'nearest'
                # plt.rcParams['figure.cmap'] = 'gray'
                num_samples = len(all_decoded)
                ran_arr = np.random.randint(num_samples, size=10)
                reference = load_pickle('./pascaldata/val/val.references.pkl')
                sample_file = open('sample.txt', 'w')
                sample_file.write('Grountruth:\n')
                for idx in ran_arr:
                    for key in reference[idx][0].split()[:-1]:
                        sample_file.write(self.model.idx_to_word[int(key)+3] +' ')
                    sample_file.write('\n')
                sample_file.write('\nSample:\n')
                for n in range(10):
                    k = ran_arr[n]
                    print "Sampled Caption: %s" % all_decoded[k]
                    sample_file.write(str(all_decoded[k]+'\n'))
                    # Plot original image
                    img = ndimage.imread(data['file_names'][k])
                    # plt.subplot(4, 5, 1)
                    # plt.imshow(img)
                    # plt.axis('off')
                    fname = 'origin' + str(n+1) + '.png'
                    fname = image_file_name + fname
                    plt.imsave(fname, img)
                    # Plot images with attention weights
                    words = all_decoded[k].split(" ")
                    for t in range(len(words)):
                        # plt.subplot(4, 5, t+2)
                        # plt.text(0, 1, '%s(%.2f)'%(words[t], bts[n,t]) , color='black', backgroundcolor='white', fontsize=8)
                        alp_curr = np.asarray(all_alphas[k][0][t][:]).reshape(14,14)
                        alp_img = skimage.transform.pyramid_expand(alp_curr, upscale=16, sigma=20)
                        fname = 'atten_' + str(n+1) + '_' + str(t) +'.png'
                        fname = image_file_name + fname
                        plt.imsave(fname, alp_img, cmap='gray')
                        # plt.axis('off')
                    # plt.show()
