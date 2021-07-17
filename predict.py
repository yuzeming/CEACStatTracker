from io import BytesIO
import torch
import string
import os
from torchvision.transforms.functional import to_tensor 
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from collections import OrderedDict

characters = '-' + string.digits + string.ascii_uppercase
width, height, n_len, n_classes = 200, 50, 6, len(characters)

captcha_pth_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "captcha.pth")

def decode(sequence):
    a = ''.join([characters[x] for x in sequence])
    s = ''.join([x for j, x in enumerate(a[:-1]) if x != characters[0] and x != a[j+1]])
    if len(s) == 0:
        return ''
    if a[-1] != characters[0] and s[-1] != a[-1]:
        s += a[-1]
    return s

class Model(nn.Module):
    def __init__(self, n_classes, input_shape):
        super(Model, self).__init__()
        self.input_shape = input_shape
        channels = [32, 64, 128, 256, 256]
        layers = [2, 2, 2, 2, 2]
        kernels = [3, 3, 3, 3, 3]
        pools = [2, 2, 2, 2, (2, 1)]
        modules = OrderedDict()
        
        def cba(name, in_channels, out_channels, kernel_size):
            modules[f'conv{name}'] = nn.Conv2d(in_channels, out_channels, kernel_size,
                                               padding=(1, 1) if kernel_size == 3 else 0)
            modules[f'bn{name}'] = nn.BatchNorm2d(out_channels)
            modules[f'relu{name}'] = nn.ReLU(inplace=True)
        
        last_channel = 3
        for block, (n_channel, n_layer, n_kernel, k_pool) in enumerate(zip(channels, layers, kernels, pools)):
            for layer in range(1, n_layer + 1):
                cba(f'{block+1}{layer}', last_channel, n_channel, n_kernel)
                last_channel = n_channel
            modules[f'pool{block + 1}'] = nn.MaxPool2d(k_pool)
        modules[f'dropout'] = nn.Dropout(0.25, inplace=True)
        
        self.cnn = nn.Sequential(modules)
        self.lstm = nn.LSTM(input_size=self.infer_features(), hidden_size=128, num_layers=2, bidirectional=True)
        self.fc = nn.Linear(in_features=256, out_features=n_classes)
    
    def infer_features(self):
        x = torch.zeros((1,)+self.input_shape)
        x = self.cnn(x)
        x = x.reshape(x.shape[0], -1, x.shape[-1])
        return x.shape[1]

    def forward(self, x):
        x = self.cnn(x)
        x = x.reshape(x.shape[0], -1, x.shape[-1])
        x = x.permute(2, 0, 1)
        x, _ = self.lstm(x)
        x = self.fc(x)
        return x


device = torch.device("cpu")
model = Model(n_classes, input_shape=(3, height, width))
model.load_state_dict(torch.load(captcha_pth_path, map_location=device))
model.eval()

def pred(img_content):
    img = Image.open(BytesIO(img_content))
    image = to_tensor(img)
    output = model(image.unsqueeze(0).cpu())
    output_argmax = output.detach().permute(1, 0, 2).argmax(dim=-1)
    pred = decode(output_argmax[0])
    # open(pred+"_test.jpg","wb").write(img_content)
    # print(pred)
    return pred


def main():
    print('pred:', pred(Image.open("test.jpg")))
    
if __name__=="__main__":
    main()

