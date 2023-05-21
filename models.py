import torch
import torch.nn as nn
from torch.nn import functional as F
from dataclasses import dataclass


@dataclass
class Config:
    vocab_size:int
    dim_embeddings: int
    dim_context: int
    num_heads: int
    n_layer: int
    dropout: int 
    bias: bool = True
    device: str = 'cpu'


class RNN(nn.Module):
    def __init__(self, vocab_size, dim_embeddings, hidden_nodes, n_classes):
        super().__init__()
        self.rnn = nn.Sequential(
                nn.Embedding(vocab_size, dim_embeddings), #(B, T) -> (B, T, D)
                nn.RNN(dim_embeddings, hidden_nodes, batch_first=True), #(B, T, D) -> ( (B,T,D) , (S, B, D)  )
                #the tanh activation is built into the RNN object, so we don't need to do it here
                LastTimeStep(), #We need to take the RNN output and reduce it to one item, (B, D)
                nn.Linear(hidden_nodes, n_classes), #(B, D) -> (B, classes)
                )

    def forward(self, x):
        logits = self.rnn(x)
        return logits
    

class LastTimeStep(nn.Module):
    """
    A class for extracting the hidden activations of the last time step following 
    the output of a PyTorch RNN module. 
    """
    def __init__(self, rnn_layers=1, bidirectional=False):
        super(LastTimeStep, self).__init__()
        self.rnn_layers = rnn_layers
        if bidirectional:
            self.num_driections = 2
        else:
            self.num_driections = 1    
    
    def forward(self, input):
        #Result is either a tupe (out, h_t)
        #or a tuple (out, (h_t, c_t))
        rnn_output = input[0]
        last_step = input[1] #this will be h_t
        if(type(last_step) == tuple):#unless it's a tuple, 
            last_step = last_step[0]#then h_t is the first item in the tuple
        batch_size = last_step.shape[1] #per docs, shape is: '(num_layers * num_directions, batch, hidden_size)'
        #reshaping so that everything is separate 
        last_step = last_step.view(self.rnn_layers, self.num_driections, batch_size, -1)
        #We want the last layer's results
        last_step = last_step[self.rnn_layers-1] 
        #Re order so batch comes first
        last_step = last_step.permute(1, 0, 2)
        #Finally, flatten the last two dimensions into one
        return last_step.reshape(batch_size, -1)


class BigramLanguageModel(nn.Module):
    def __init__(self, vocab_size):
        super().__init__()
        self.token_embedding_table = nn.Embedding(vocab_size, vocab_size)

    def forward(self, idx):
        logits = self.token_embedding_table(idx) 
        return logits


class simpleGPT(nn.Module):
    def __init__(self, vocab_size, n_embd, num_heads, block_size, n_layer, dropout, device):
        super().__init__()
        self.token_embedding_table = nn.Embedding(vocab_size, n_embd)
        self.position_embedding_table = nn.Embedding(block_size, n_embd)
        self.blocks = nn.Sequential(*[Block(n_embd, n_head=num_heads, block_size=block_size, dropout=dropout) for _ in range(n_layer)])
        self.ln_f = nn.LayerNorm(n_embd)
        self.lm_head = nn.Linear(n_embd, vocab_size)
        self.device = device

    def forward(self, idx):
        B, T = idx.shape
        tok_emb = self.token_embedding_table(idx) 
        positinal_emb = self.position_embedding_table(torch.arange(T, device=self.device))
        x = tok_emb + positinal_emb
        x = self.blocks(x)
        logits = self.lm_head(x)
        return logits
    

class GPT1(nn.Module):
    def __init__(self, config: Config):
        super().__init__()
        self.token_embedding_table = nn.Embedding(config.vocab_size, config.dim_embeddings)
        self.position_embedding_table = nn.Embedding(config.dim_context, config.dim_embeddings)
        self.blocks = nn.Sequential(*[BlockGPT1(config.dim_embeddings, config.num_heads, config.dim_context, config.dropout) for _ in range(config.n_layer)])
        self.lm_head = nn.Linear(config.dim_embeddings, config.vocab_size)
        self.device = config.device

    def forward(self, idx):
        T = idx.shape[-1]
        embedding_token = self.token_embedding_table(idx) 
        embedding_position = self.position_embedding_table(torch.arange(T, device=self.device))
        x = embedding_token + embedding_position 
        x = self.blocks(x)
        logits = self.lm_head(x)
        return logits
    

class GPT2(nn.Module):
    def __init__(self, config: Config):
        super().__init__()
        self.token_embedding_table = nn.Embedding(config.vocab_size, config.dim_embeddings)
        self.position_embedding_table = nn.Embedding(config.dim_context, config.dim_embeddings)
        self.drop = nn.Dropout(config.dropout)
        self.blocks = nn.Sequential(*[BlockGPT2(config.dim_embeddings, config.num_heads, config.dim_context, config.bias, config.dropout) for _ in range(config.n_layer)])
        self.lm_head = nn.Linear(config.dim_embeddings, config.vocab_size)
        self.device = config.device

    def forward(self, idx):
        T = idx.shape[-1]
        embedding_token = self.token_embedding_table(idx) 
        embedding_position = self.position_embedding_table(torch.arange(T, device=self.device))
        x = self.drop(embedding_token + embedding_position)
        x = self.blocks(x)
        logits = self.lm_head(x)
        return logits


class LayerNorm(nn.Module):
    """ LayerNorm but with an optional bias. PyTorch doesn't support simply bias=False """

    def __init__(self, ndim, bias):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(ndim))
        self.bias = nn.Parameter(torch.zeros(ndim)) if bias else None

    def forward(self, input):
        return F.layer_norm(input, self.weight.shape, self.weight, self.bias, 1e-5)
     

class FeedFowardGPT2(nn.Module):
    def __init__(self, n_embd, dropout=0.0):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_embd, 4 * n_embd),
            nn.GELU(),
            nn.Linear(4 * n_embd, n_embd),
            nn.Dropout(dropout),
        )
    
    def forward(self, x):
        return self.net(x)


class FeedFoward(nn.Module):
    def __init__(self, n_embd, dropout=0.0):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_embd, 4 * n_embd),
            nn.ReLU(),
            nn.Linear(4 * n_embd, n_embd),
            nn.Dropout(dropout),
        )
    
    def forward(self, x):
        return self.net(x)


class Head(nn.Module):
    """ one head of self-attention """

    def __init__(self, head_size, n_embd, block_size, dropout=0.0):
        super().__init__()
        self.key = nn.Linear(n_embd, head_size, bias=False)
        self.query = nn.Linear(n_embd, head_size, bias=False)
        self.value = nn.Linear(n_embd, head_size, bias=False)
        self.register_buffer('tril', torch.tril(torch.ones(block_size, block_size)))
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        T = x.shape[-2]
        k = self.key(x)   
        q = self.query(x) 
        wei = q @ k.transpose(-2,-1) * k.shape[-1]**-0.5 
        wei = wei.masked_fill(self.tril[:T, :T] == 0, float('-inf'))
        wei = F.softmax(wei, dim=-1) 
        wei = self.dropout(wei)
        v = self.value(x) 
        out = wei @ v 
        return out
    

class MultiHeadAttention(nn.Module):
    """ multiple heads of self-attention in parallel """

    def __init__(self, num_heads, head_size, n_embd, block_size, dropout=0.0):
        super().__init__()
        self.heads = nn.ModuleList([Head(head_size, n_embd, block_size, dropout) for _ in range(num_heads)])
        self.proj = nn.Linear(n_embd, n_embd)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        out = torch.cat([h(x) for h in self.heads], dim=-1)
        out = self.proj(out)
        out = self.dropout(out)
        return out
    
class Block(nn.Module):
    """ Transformer block: communication followed by computation """

    def __init__(self, n_embd, n_head, block_size, dropout=0.0):
        # n_embd: embedding dimension, n_head: the number of heads we'd like
        super().__init__()
        head_size = n_embd // n_head
        self.sa = MultiHeadAttention(n_head, head_size, n_embd, block_size, dropout)
        self.ffwd = FeedFoward(n_embd, dropout)
        self.ln1 = nn.LayerNorm(n_embd)
        self.ln2 = nn.LayerNorm(n_embd)


    def forward(self, x):
        x = x + self.sa(self.ln1(x))
        x = x + self.ffwd(self.ln2(x))
        return x
    
class BlockGPT1(nn.Module):
    def __init__(self, n_embd, n_head, block_size, dropout=0.0):
        super().__init__()
        head_size = n_embd // n_head
        self.multi_head = MultiHeadAttention(n_head, head_size, n_embd, block_size, dropout)
        self.ffwd = FeedFoward(n_embd, dropout)
        self.ln1 = nn.LayerNorm(n_embd)
        self.ln2 = nn.LayerNorm(n_embd)


    def forward(self, x):
        x = self.multi_head(x) + x
        x = self.ln1(x)
        x = self.ffwd(x) + x
        x = self.ln2(x)
        return x
    

class BlockGPT2(nn.Module):
    def __init__(self, n_embd, n_head, block_size, bias, dropout=0.0):
        super().__init__()
        head_size = n_embd // n_head
        self.multi_head = MultiHeadAttention(n_head, head_size, n_embd, block_size, dropout)
        self.ffwd = FeedFowardGPT2(n_embd, dropout)
        self.ln1 = LayerNorm(n_embd, bias)
        self.ln2 = LayerNorm(n_embd, bias)


    def forward(self, x):
        x = x + self.multi_head(self.ln1(x)) 
        x = x + self.ffwd(self.ln2(x)) 
        return x
   
    
def generate(model, idx, max_new_tokens, block_size=None):
    model.eval()
    for _ in range(max_new_tokens):
        if block_size is None:
            idx_cond = idx
        else: 
            idx_cond = idx[:, -block_size:]
        logits = model(idx_cond)
        logits = logits[:, -1, :]
        probs = F.softmax(logits, dim=-1) 
        idx_next = torch.multinomial(probs, num_samples=1) 
        idx = torch.cat((idx, idx_next), dim=1) 
    return idx
