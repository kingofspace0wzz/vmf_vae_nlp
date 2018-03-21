###############################################################################
# Language Modeling on Penn Tree Bank
#
# This file generates new sentences sampled from the language model
#
###############################################################################
import logging
import argparse
import math
import torch
from torch.autograd import Variable
from vae_proto import vae_rnn
from vae_proto import pure_rnn
from vae_proto import data
from vae_proto import util

parser = argparse.ArgumentParser(description='PyTorch Wikitext-2 Language Model')

# Model parameters.
parser.add_argument('--model', type=str,default='vae')
parser.add_argument('--eval_batch_size', type=int, default=5, help='evaluation batch size')
parser.add_argument('--data', type=str, default='../data/ptb',
                    help='location of the data corpus')
parser.add_argument('--checkpoint', type=str, default='model.pt',
                    help='model checkpoint to use')
parser.add_argument('--outf', type=str, default='generated.txt',
                    help='output file for generated text')
# parser.add_argument('--words', type=int, default='1000',help='number of words to generate')
parser.add_argument('--seed', type=int, default=1111,
                    help='random seed')
parser.add_argument('--cuda', action='store_true',
                    help='use CUDA',default=False)
parser.add_argument('--temperature', type=float, default=1.0,
                    help='temperature - higher will increase diversity')
parser.add_argument('--log-interval', type=int, default=100,
                    help='reporting interval')
args = parser.parse_args()

fname = 'Result_Model_{}_checkpoint_{}.log'.format(args.model,args.checkpoint)
print(fname)

logging.basicConfig(filename=fname, level=logging.INFO)

# Set the random seed manually for reproducibility.
torch.manual_seed(args.seed)
if torch.cuda.is_available():
    if not args.cuda:
        print("WARNING: You have a CUDA device, so you should probably run with --cuda")
    else:
        torch.cuda.manual_seed(args.seed)

if args.temperature < 1e-3:
    parser.error("--temperature has to be greater or equal 1e-3")

with open(args.model+args.checkpoint, 'rb') as f:
    model = torch.load(f)
model.eval()

if args.cuda:
    model.cuda()
else:
    model.cpu()

corpus = data.Corpus(args.data)
ntokens = len(corpus.dictionary)


test_data = util.make_batch(args,corpus.test, args.eval_batch_size, shuffle=False)

nll = util.decode_inputless(args, model, corpus, test_data)
ppl = math.exp(nll)
print(nll, ppl)


# hidden = model.init_hidden(1)
# input = Variable(torch.rand(1, 1).mul(ntokens).long(), volatile=True)
# if args.cuda:
#     input.data = input.data.cuda()
#
# with open(args.outf, 'w') as outf:
#     for i in range(args.words):
#         output, hidden = model(input, hidden)
#         word_weights = output.squeeze().data.div(args.temperature).exp().cpu()
#         word_idx = torch.multinomial(word_weights, 1)[0]
#         input.data.fill_(word_idx)
#         word = corpus.dictionary.idx2word[word_idx]
#
#         outf.write(word + ('\n' if i % 20 == 19 else ' '))
#
#         if i % args.log_interval == 0:
#             print('| Generated {}/{} words'.format(i, args.words))
