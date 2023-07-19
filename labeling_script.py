'''
Cell Lineage Identification Script

This script is designed to perform cell identification tracking using a combination of
spatial, visual, and morphological features. It imports raw data, preprocesses the data,
trains an autoencoder for visual feature extraction, and then performs frame-by-frame
pairwise cell labeling to identify and track cells across frames.

Inputs:
    Original cell images as .tif file
    Cell masks output by Cellpose as .tif file
    Segmentation information generated by AREA as .csv file
    Channel name for visual feature extraction
    Maximum search radius for cell identification across frames
    Whether to import preprocessing steps

Outputs:
    Information dataframe with cell labels as .csv file
    Trained autoencoder model saved as an .h5 file
    Encoded cell images saved as .npz file

Dependencies:
    os
    sys
    pandas
    sklearn
    tensorflow
    scipy
    lineage_managment
    img_processing
    frame_by_frame

@author: Shani Zuniga
'''
import os
import sys

import numpy as np
import pandas as pd

from sklearn.model_selection import train_test_split
from tensorflow import get_logger, keras
from keras.callbacks import EarlyStopping

from utils.lineage_management import Library
from utils.img_processing import read_multiframe_tif, extract_cells
from utils.frame_by_frame import frame_by_frame

get_logger().setLevel('ERROR')
# USER INPUTS #################################################################

# Path for original cell images as .tif file
imgs_path = "data\RFP_GFP_MIDDLE5\RFP_GFP_MIDDLE5.tif"

# Path for cell masks ouput by Cellpose as .tif file
masks_path = "data\RFP_GFP_MIDDLE5\seg_RFP_GFP_MIDDLE5.tif"

# Path for segmentation information generated by AREA as .csv file
info_path = "data\RFP_GFP_MIDDLE5\EXP_MIDDLE5_1.csv"

# Channel name to use visual feature extraction on, as a string
channel = "RFP"

# Numerical value for max distance of which cells need for consideration
search_radius = 50

# Numerical value for minimum frames per lineage
min_connectivity = 10

# Whether preprocessing steps have already been completed, else will be saved
import_preprocessing = True

### PART 1: Import data and Preprocessing######################################
print("IMPORTING DATA AND PREPROCESSING...")

# 1. Import data and check that paths are valid
if (os.path.exists(imgs_path) and os.path.exists(masks_path) and 
    os.path.exists(info_path)):
    masks = read_multiframe_tif(masks_path)
    info_df = pd.read_csv(info_path)
else:
    print('ERROR: Input data not found. Check path names.')
    sys.exit(0)

# 2. Pre-processing informational data (channel, centroid extraction)
df = info_df[['Frame', 'ROI']].copy()
df = df[info_df['Channel'] == channel]
centroids = (
    info_df['Centroid']
    .str.strip('()')
    .str.split(', ', expand=True)
    .astype(float)
    )
df[['x', 'y']] = centroids

# 3. Import or generate encoded cell vectors
folder_path, file_name_with_ext = os.path.split(imgs_path)
file_name, file_ext = os.path.splitext(file_name_with_ext)

new_folder_path = os.path.join(folder_path, file_name + '_FLUORA')
vectors_path = os.path.join(new_folder_path, 'encoded_cells.npz')
encoder_path = os.path.join(new_folder_path, 'cell_encoder.h5')

if import_preprocessing and (os.path.exists(new_folder_path)):
    if os.path.exists(vectors_path):
        pass
    else:
        print('ERROR: Preprocessed data not found.')
        sys.exit(0)
    with np.load(vectors_path) as data_read:
        cell_vectors = {key: data_read[key] for key in data_read.files}
    
    print("PREPROCESSED DATA IMPORTED.")
else:
    if not os.path.exists(new_folder_path):
        os.makedirs(new_folder_path)

    # 4. Extract cells and generate cell imgs. (img name e.g., 'frame_0_cell_1')
    unique_channels = info_df['Channel'].unique().tolist()
    channel_list = [1 if channel == option else 0 for option in unique_channels]

    cell_dict = extract_cells(imgs_path, masks_path, channel_list)

    x_train = np.array(list(cell_dict.values()))
    x_train = x_train.reshape(x_train.shape[0], 28, 28, 1)
    x_train, x_test = train_test_split(x_train, test_size=0.2, random_state=42)

    early_stop = EarlyStopping(monitor='val_loss', patience=5)

    # 5. Train autoencoder on the single cell images, save encoder model
    encoder = keras.models.Sequential([
        keras.layers.Flatten(input_shape=[28, 28]),
        keras.layers.Dense(100, activation="relu"),
        keras.layers.Dense(30, activation="relu"),
        ])
    decoder = keras.models.Sequential([
        keras.layers.Dense(100, activation="relu", input_shape=[30]),
        keras.layers.Dense(28 * 28, activation="sigmoid"),
        keras.layers.Reshape([28, 28])
        ])
    autoencoder = keras.models.Sequential([encoder, decoder])
    autoencoder.compile(loss="binary_crossentropy",
                    optimizer='adam')
    autoencoder.fit(x_train, x_train, epochs=100, validation_data=[x_test, x_test],
                    callbacks=[early_stop], verbose=0) 
    del x_train, x_test

    # 6. Get latent vectors and save to file
    cell_names = np.array(list(cell_dict.keys()))
    cell_images = np.stack(list(cell_dict.values()), axis=0)

    cell_vectors = encoder.predict(cell_images, verbose=0)
    cell_vectors = dict(zip(cell_names, cell_vectors))
    np.savez(vectors_path, **cell_vectors)
    encoder.save(encoder_path)
    del cell_dict, cell_images

    print("PREPROCESSING COMPLETE.")

### PART 2: Frame-by-frame Pairwise Cell Labeling##############################

#7. Generate library of cells and their lineages
lib = Library(masks[0], df)

#8. Perform frame-by-frame pairwise cell labeling
lib = frame_by_frame(
    lib,
    masks,
    df,
    cell_vectors,
    search_radius,
    min_connectivity
    )

### PART 3: Preview and Export Results#########################################

#9. Preview results
results = lib.to_dataframe()
results = results.rename(columns={'cell_id':'ROI', 'lineage_id':'Label'})
results['ROI'] -= 1

final_df = info_df.merge(results, on=['ROI', 'Frame'], how='left')

from pandasgui import show
show(final_df)