from core.solver_iterative_update import CaptioningSolver
from core.model_iterative_update import CaptionGenerator
from core.utils_pascal import *
import os
import sys
os.environ['CUDA_VISIBLE_DEVICES']='0'

modelname = sys.argv[1]
filename = sys.argv[2]
thres = sys.argv[3]
print '#########################'
print 'model = ' + modelname
print 'thres = ' + thres
print '#########################'

def main():
    word_to_idx = load_word_to_idx(data_path='./pascaldata', split='train')
    # val_data = load_pascal_data(data_path='./pascaldata', split='val', load_init_pred=True)
    test_data = load_pascal_data(data_path='./pascaldata', split='test', load_init_pred=True)
    model = CaptionGenerator(word_to_idx, dim_feature=[196, 1024], dim_embed=64,
                            dim_hidden=1024, n_time_step=16, prev2out=True,
                            ctx2out=True, alpha_c=1.0, selector=True, dropout=True)
    data_path = './pascaldata'
    solver = CaptioningSolver(model, data_path, n_epochs=200, batch_size=1,
                update_rule='adam', learning_rate=0.0005, print_every=100, save_every=1,
                pretrained_model=None, model_path='model/lstm/',
                test_model=('model/lstm/%s' %modelname), print_bleu=True, log_path='log/',
                V=len(word_to_idx))
    solver.test(test_data, split='test', filename=filename, attention_visualization=False,\
                thres=float(thres))

if __name__ == "__main__":
    main()
