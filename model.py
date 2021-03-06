#STEP 1: First we parse the arguments
import sys
import argparse

parser = argparse.ArgumentParser(description='Model training')
parser.add_argument(
    'training_dir',
    type=str,
    help='path to training directory e.g. recordings/driving_iram_1.'
)
parser.add_argument(
    'model',
    type=int,
    help='The model type: 1 (Basic), 2 (LeNet), 3 (Nvidia)'
)
parser.add_argument(
    'flip',
    type=int,
    nargs='?',
    default=1,
    help='1(flip image to augment data), 1(default, also flip images)'
)
parser.add_argument(
    'reuse',
    type=int,
    nargs='?',
    default=1,
    help='1(Reuse the model), 0(Create new model). Default is 1.'
)

args = parser.parse_args()
model_file=''
if args.model == 1:
    model_file='basic.h5'
elif args.model == 2:
    model_file='lenet.h5'
else:
    model_file='nvidia.h5'
    
reuse=True
if args.reuse == 0:
    reuse=False
    
training_dir=args.training_dir
if training_dir[-1] != '/':
    training_dir += '/'

flip=True
if args.flip == 0:
    flip=False
    
print('------------------------------------')
print('training data: ', training_dir, '\nmodel file: ', model_file, '\nreuse model file(if present): ', reuse, '\nflip images: ', flip)
print('------------------------------------')

proceed=input('Please review the above input arguments, Proceed with training (y/n)?')
if proceed != 'y':
    print('Exiting program.')
    sys.exit()


#STEP 2: load images
import csv
import cv2
import numpy as np
from os import listdir
from os.path import isdir, join
import glob


samples=[]

#track 2 we need to keep a value of .1
#but for track 1 it needs to be reduced to say .002
min_t1_thres=.002
min_t2_thres=.1
zero_drop_prob=0.9

#reads a high level dir e.g. one for each track
#which has various folers within
def load_all_sub_dirs(tdir):
    load_from_dir(tdir)
    onlydirs = [f for f in listdir(tdir) if isdir(join(tdir, f))]
    #print(onlydirs)
    for adir in onlydirs:
        #print(tdir + adir)
        load_from_dir(tdir + adir + "/")
        #recursively call itself for each dir (in case we club t1/t2)
        if tdir[-1] != '/':
            tdir += '/'
        load_all_sub_dirs(tdir+adir)


def append_line(local_path, img_path, measurement, flipped=False):
     entry=[None]*3
     entry[0]= local_path +"IMG/" + img_path.split('/')[-1]
     entry[1]=measurement
     entry[2]=flipped
     samples.append(entry)

def load_from_dir(local_path):
    csv_files = glob.glob(local_path+"driving_log.csv")
    if len(csv_files)>0:
        csvn = csv_files[0]
        print("loading: ", csvn)
        with open(csvn) as csvfile:
            reader = csv.reader(csvfile)
            for line in reader:
                # appending the local path for relative img path location
                correction = 0.2
                entry=[None]*3
                measurement=float(line[3])
                
                # We drop near zero steering angle with a high probablity
                if abs(measurement)<=min_t1_thres:
                    if np.random.uniform() < zero_drop_prob:
                        continue


                #center line
                append_line(local_path, line[0], measurement)
                #left line
                append_line(local_path, line[1], measurement + correction)
                #right line
                append_line(local_path, line[2], measurement - correction)
                if flip:
                    #center line
                    append_line(local_path, line[0], -measurement, True)
                    #left line
                    append_line(local_path, line[1], -(measurement + correction), True)
                    #right line
                    append_line(local_path, line[2], -(measurement - correction), True)

load_all_sub_dirs(training_dir)
print('no. of images: ', len(samples))

from sklearn.model_selection import train_test_split
train_samples, validation_samples = train_test_split(samples, test_size=0.1)
print('training samples: ', len(train_samples))
print('validation samples: ', len(validation_samples))


#This idea and code of lateral tranformation of an image 
# to get more data is inspired and copied from
#https://chatbotslife.com/using-augmentation-to-mimic-human-driving-496b569760a9
def trans_image(image,steer,trans_range):
    # Translation
    tr_x = trans_range*np.random.uniform()-trans_range/2
    steer_ang = steer + tr_x/trans_range*2*.2
    tr_y = 40*np.random.uniform()-40/2
    #tr_y = 0
    Trans_M = np.float32([[1,0,tr_x],[0,1,tr_y]])
    image_tr = cv2.warpAffine(image,Trans_M,(320,160))
    
    return image_tr,steer_ang


import sklearn

def get_image_and_meas(local_path, image_path, measurement):
    #print(img_fname)
    image = cv2.imread(img_fname)
    angle = measurement
    return image, angle

def generator(samples, batch_size=256):
    num_samples = len(samples)
    while 1: # Loop forever so the generator never terminates
        sklearn.utils.shuffle(samples)
        for offset in range(0, num_samples, batch_size):
            batch_samples = samples[offset:offset+batch_size]

            images = []
            angles = []
            for batch_sample in batch_samples:
                img = cv2.imread(batch_sample[0])
                if batch_sample[2]:
                    img=np.fliplr(img)
                #images.append(img)
                meas = batch_sample[1]
                #angles.append(meas)
                #transform image (left/right shift) for more data
                track1_pixels=50
                track2_pixels=140
                img_trans, y_trans = trans_image(img, meas, track1_pixels)
                images.append(img_trans)
                angles.append(y_trans)

            # trim image to only see section with road
            X_train = np.array(images)
            y_train = np.array(angles)
            yield sklearn.utils.shuffle(X_train, y_train)

# compile and train the model using the generator function
train_generator = generator(train_samples, batch_size=32)
validation_generator = generator(validation_samples, batch_size=32)

#Now the model
from keras.models import Sequential
from keras.models import load_model
from keras.layers import Flatten, Dense, Lambda, Cropping2D, Conv2D, MaxPooling2D
#from keras import backend as ktf

def createBasicModel():
    model = Sequential()
    model.add(Lambda(lambda x: x/255.0 - 0.5, input_shape = (160, 320, 3)))
    model.add(Cropping2D(cropping=((50,20), (0,0))))
    model.add(Flatten())
    model.add(Dense(1))
    model.compile(loss='mse', optimizer='adam')
    return model

def createLeNetModel():
    model = Sequential()
    model.add(Lambda(lambda x: x/255.0 - 0.5, input_shape = (160, 320, 3)))

    #Since resize is problematic, using MaxPooling2D should give same effect
    model.add(MaxPooling2D())

    #output of crop 90x320
    model.add(Cropping2D(cropping=((25,10), (0,0))))
    
    #first cnn layers
    #output of this layer 88x318x6
    model.add(Conv2D(
        # new versions of keras have better way of giving input means 6, (3,3)
        # the keras documentation is for the latest version (slightly diff from here)
        6, 3, 3,
        border_mode='valid',
        activation='relu',
))

    #output 44x159x6
    model.add(MaxPooling2D())

    #2nd conv layer 
    #output 40x155x16 
    model.add(Conv2D(
        16, 5, 5,
        border_mode='valid',
        activation='relu',
))

    #output 20x77x16
    model.add(MaxPooling2D())
    
    # output 24640 
    model.add(Flatten())
    
    # fc 1 output 300
    # this will need huge(st) no. of params
    model.add(Dense(300))

    #bringing it down to single output
    model.add(Dense(1))

    model.compile(loss='mse', optimizer='adam')
    return model


def resize(img):
    #We must import it inside the function
    #because its used from a lambda layer
    import tensorflow as tf
    return tf.image.resize_images(img, (66, 235))

def createNvidiaModel():
    model = Sequential()
    #resize images in a lambda layer 
    #courtesy http://stackoverflow.com/questions/42260265/resizing-an-input-image-in-a-keras-lambda-layer
    #model.add(Lambda(lambda img: ktf.resize_images(img, 160/160, 320/320, 'tf'),
    #                 input_shape=(160, 320, 3)))


    #output of crop 90x320
    model.add(Cropping2D(cropping=((50,20), (0,0)), input_shape=(160, 320, 3)))
    
    #resize images
    model.add(Lambda(resize))
    
    #normalize
    model.add(Lambda(lambda x: x/255.0 - 0.5))

    #1st cnn layer
    #output of this layer 43x158x24
    model.add(Conv2D(
        24, 5, 5, 
        subsample=(2,2),
        activation='relu',
        border_mode='valid'
))

    #2nd cnn layer
    #output of this layer 20x77x36
    model.add(Conv2D(
        36, 5, 5, 
        subsample=(2,2),
        activation='relu',
        border_mode='valid'
))

    #3rd cnn layer
    #output of this layer 8x37x48
    model.add(Conv2D(
        48, 5, 5, 
        subsample=(2,2),
        activation='relu',
        border_mode='valid'
))

    #4th cnn layer
    #output of this layer 6x35x64
    model.add(Conv2D(
        64, 3, 3, 
        activation='relu',
        border_mode='valid'
))

    #5th cnn layer
    #output of this layer 4x33x64
    model.add(Conv2D(
        64, 3, 3, 
        activation='relu',
        border_mode='valid'
))

    # output: 3968
    model.add(Flatten())
    
    #fc1 
    model.add(Dense(100))

    #fc2 
    model.add(Dense(50))

    #fc3 
    model.add(Dense(10))

    #single output (which maps to steering o/p)
    model.add(Dense(1))

    model.compile(loss='mse', optimizer='adam')
    return model


def load_model_from_file():
    if reuse:
        try:
            model = load_model(model_file)
            return model
        except:
            print('Error in loading model from file:', model_file)

    my_model=None
    if args.model == 1:
        my_model = createBasicModel()
    if args.model == 2:
        my_model = createLeNetModel()
    if args.model == 3:
        my_model = createNvidiaModel()
    
    my_model.summary()
    return my_model

model = load_model_from_file()
#model.fit(X_train, y_train, validation_split=0.2, shuffle=True, nb_epoch=7)
model.fit_generator(train_generator, samples_per_epoch= \
            len(train_samples), validation_data=validation_generator, \
            nb_val_samples=len(validation_samples), nb_epoch=5)
model.save(model_file)
