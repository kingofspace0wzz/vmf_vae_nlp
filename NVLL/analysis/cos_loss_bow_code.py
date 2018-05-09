from collections import OrderedDict
from operator import itemgetter

from NVLL.data.lm import DataLM
from NVLL.model.nvrnn import RNNVAE
from NVLL.framework.run_nvrnn import Runner
from NVLL.util.util import GVar
import os
import argparse

import torch

def load_args(path, name):
    with open(os.path.join(path, name + '.args'), 'rb') as f:
        args = torch.load(f)
    return args


def load_data(data_path, eval_batch_siez, condition):
    data = DataLM(data_path, eval_batch_siez, eval_batch_siez, condition)
    return data


def load_model(args, ntoken, path, name):
    model = RNNVAE(args, args.enc_type, ntoken, args.emsize,
                   args.nhid, args.lat_dim, args.nlayers,
                   dropout=args.dropout, tie_weights=args.tied,
                   input_z=args.input_z, mix_unk=args.mix_unk,
                   condition=(args.cd_bit or args.cd_bow),
                   input_cd_bow=args.cd_bow, input_cd_bit=args.cd_bit)
    print("Loading {}".format(name))
    model.load_state_dict(torch.load(os.path.join(path, name + '.model')))
    from NVLL.util.gpu_flag import GPU_FLAG
    if torch.cuda.is_available() and GPU_FLAG:
        model = model.cuda()
    model = model.eval()
    return model


def parse_arg():
    parser = argparse.ArgumentParser(description='Transfer experiment')
    parser.add_argument('--data_path', type=str, default='data/yelp', help='location of the data corpus')
    parser.add_argument('--root_path', type=str, default='/home/cc/vae_txt')
    parser.add_argument('--model_vmf', type=str, default="Datayelp_Distvmf_Modelnvrnn_EnclstmBiFalse_Emb100_Hid400_lat100_lr10.0_drop0.5_kappa200.0_auxw0.0001_normfFalse_nlay1_mixunk1.0_inpzTrue_cdbit50_cdbow0_4.9021353610814655")
    parser.add_argument('--model_nor', type=str, default="Datayelp_Distnor_Modelnvrnn_EnclstmBiFalse_Emb100_Hid400_lat100_lr10.0_drop0.5_kappa0.1_auxw0.0001_normfFalse_nlay1_mixunk1.0_inpzTrue_cdbit50_cdbow0_5.545100331287798")
    parser.add_argument('--exp_path', type=str, default='/home/cc/save-nvrnn')
    parser.add_argument('--eval_batch_size', type=int, default=10, help='evaluation batch size')
    parser.add_argument('--batch_size', type=int, default=10, help='batch size')

    args = parser.parse_args()
    return args

class Transfer():
    @staticmethod
    def write_word_embedding(exp_path, file_name, word_list, embedding_mat):
        embedding_mat = embedding_mat.data
        path  =os.path.join(exp_path, file_name)
        print("To save {}".format(os.path.join(exp_path, file_name)))
        bag = []
        for idx, w in enumerate(word_list):
            name = w[0]
            emb = embedding_mat[idx]
            l = [name ]+ emb.tolist()
            l = [ str(x) for x in l]
            l = " ".join(l)
            bag.append(l)

        s = "\n".join(bag)
        with open(path, 'w') as fd:
            fd.write(s)

    def __init__(self, args):
        self.data = DataLM(os.path.join(args.root_path, args.data_path),
                      args.batch_size,
                      args.eval_batch_size,
                      condition=True)
        word_list = sorted(self.data.dictionary.word2idx.items(), key=itemgetter(1))

        vmf_args = load_args(args.exp_path, args.model_vmf)
        vmf_model = load_model(vmf_args,                                          len(self.data.dictionary), args.exp_path, args.model_vmf)
        vmf_emb = vmf_model.emb.weight
        self.write_word_embedding(args.exp_path, args.model_vmf+'_emb', word_list,vmf_emb)
        nor_args = load_args(args.exp_path, args.model_nor)
        nor_model = load_model(nor_args, len(self.data.dictionary), args.exp_path, args.model_nor)
        nor_emb = nor_model.emb.weight
        self.write_word_embedding(args.exp_path, args.model_nor + '_emb', word_list, nor_emb)

def synthesis_bow_rep(args):
    data = DataLM(os.path.join(args.root_path, args.data_path),
                       args.batch_size,
                       args.eval_batch_size,
                       condition=True)
import random

class Code2Code(torch.nn.Module):
    def __init__(self, inp_dim, tgt_dim):
        super().__init__()
        self.linear = torch.nn.Linear(inp_dim, tgt_dim)
        self.linear2 = torch.nn.Linear(tgt_dim, tgt_dim)

        self.loss_func = torch.nn.CosineEmbeddingLoss()

    def forward(self, inp, tgt):
        pred = self.linear(inp)
        pred = torch.nn.functional.tanh(pred)
        pred = self.linear2(pred)
        # print(pred.size())
        loss = 1 - torch.nn.functional.cosine_similarity(pred, tgt)
        loss = torch.mean(loss)
        return loss

class CodeLearner():

    def __init__(self,args):
        self.data = DataLM(os.path.join(args.root_path, args.data_path),
                      args.batch_size,
                      args.eval_batch_size,
                      condition=True)
        self.args = load_args(args.exp_path, args.model_nor)
        self.model = load_model(self.args, len(self.data.dictionary),
                                    args.exp_path, args.model_nor)
        self.learner = Code2Code( self.model.lat_dim,self.model.ninp)
        self.learner.cuda()
        self.optim = torch.optim.SGD(self.learner.parameters(), lr=0.0001)
        self.run_train()
    def run_train(self):
        for e in range(40):
            self.train_epo(self.data.train)

    def train_epo(self, train_batches):
        self.learner.train()
        print("Epo start")
        acc_loss = 0
        cnt = 0

        random.shuffle(train_batches)
        for idx, batch in enumerate(train_batches):
            self.optim.zero_grad()
            seq_len, batch_sz = batch.size()
            if self.data.condition:
                seq_len -= 1

                if self.model.input_cd_bit > 1:
                    bit = batch[0, :]
                    bit = GVar(bit)
                else:
                    bit = None
                batch = batch[1:, :]
            else:
                bit = None
            feed = self.data.get_feed(batch)

            seq_len, batch_sz = feed.size()
            emb = self.model.drop(self.model.emb(feed))

            if self.model.input_cd_bit > 1:
                bit = self.model.enc_bit(bit)
            else:
                bit = None

            h = self.model.forward_enc(emb, bit)
            tup, kld, vecs = self.model.forward_build_lat(h)  # batchsz, lat dim
            if self.model.dist_type == 'vmf':
                code = tup['mu']
            elif self.model.dist_type == 'nor':
                code = tup['mean']
            else:
                raise  NotImplementedError
            emb = torch.mean(emb,dim=0)
            # print(emb.size())
            # print(code.size())
            loss = self.learner(code,emb)

            loss.backward()
            self.optim.step()
            acc_loss += loss.data[0]
            cnt += 1
            if idx %20 == 0:
                print(acc_loss/ cnt)
                acc_loss = 0
                cnt = 0
    def evaluate(self, args, model, dev_batches):

        # Turn on training mode which enables dropout.
        model.eval()
        model.FLAG_train = False

        acc_loss = 0
        acc_kl_loss = 0
        acc_aux_loss = 0
        acc_avg_cos = 0
        acc_avg_norm = 0

        batch_cnt = 0
        all_cnt = 0
        cnt = 0
        start_time = time.time()

        for idx, batch in enumerate(dev_batches):

            seq_len, batch_sz = batch.size()
            if self.data.condition:
                seq_len -= 1
                bit = batch[0, :]
                batch = batch[1:, :]
                bit = GVar(bit)
            else:
                bit = None
            feed = self.data.get_feed(batch)

            if self.args.swap > 0.00001:
                feed = swap_by_batch(feed, self.args.swap)
            if self.args.replace > 0.00001:
                feed = replace_by_batch(feed, self.args.replace, self.model.ntoken)

            target = GVar(batch)

            recon_loss, kld, aux_loss, tup, vecs, _ = model(feed, target, bit)

            acc_loss += recon_loss.data * seq_len * batch_sz
            acc_kl_loss += torch.sum(kld).data
            acc_aux_loss += torch.sum(aux_loss).data
            acc_avg_cos += tup['avg_cos'].data
            acc_avg_norm += tup['avg_norm'].data
            cnt += 1
            batch_cnt += batch_sz
            all_cnt += batch_sz * seq_len

        cur_loss = acc_loss[0] / all_cnt
        cur_kl = acc_kl_loss[0] / all_cnt
        cur_aux_loss = acc_aux_loss[0] / all_cnt
        cur_avg_cos = acc_avg_cos[0] / cnt
        cur_avg_norm = acc_avg_norm[0] / cnt
        cur_real_loss = cur_loss + cur_kl

        # Runner.log_eval(print_ppl)
        # print('loss {:5.2f} | KL {:5.2f} | ppl {:8.2f}'.format(            cur_loss, cur_kl, math.exp(print_ppl)))
        return cur_loss, cur_kl, cur_real_loss

if __name__ == '__main__':
    print("Transfer btw Learnt Code and learnt BoW. "
          "Assume data is Yelp and model is vMF or nor.")
    args = parse_arg()
    # t = Transfer(args)
    # Synthesis data
    learn = CodeLearner(args)
    # Learn !!
