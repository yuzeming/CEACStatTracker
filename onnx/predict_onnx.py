import onnxruntime as ort
import numpy as np
from PIL import Image
import string
from io import BytesIO

characters = '-' + string.digits + string.ascii_uppercase
width, height, n_len, n_classes = 200, 50, 6, len(characters)

def decode(sequence):
    a = ''.join([characters[x] for x in sequence])
    s = ''.join([x for j, x in enumerate(a[:-1]) if x != characters[0] and x != a[j+1]])
    if len(s) == 0:
        return ''
    if a[-1] != characters[0] and s[-1] != a[-1]:
        s += a[-1]
    return s


def pred(img_content):
    img = np.asarray( Image.open(BytesIO(img_content)) ,dtype=np.float32) / 255.0
    img = np.expand_dims(np.transpose(img,(2,0,1)), axis=0)
    ort_sess = ort.InferenceSession('captcha.onnx')
    outputs = ort_sess.run(None, {'input': img})
    x = outputs[0]
    t = np.argmax( np.transpose(x,(1,0,2)), -1)
    pred = decode(t[0])
    return pred
    
def main():
    print('pred:', pred(open("test.jpg","rb").read()))
    
if __name__=="__main__":
    main()
