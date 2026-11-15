#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os, sys, glob
import argparse
import random
import numpy as np
import SimpleITK as sitk
from scipy import ndimage

#sys.path.insert(1, '../')
sys.path.insert(1, '/home/florent/Code/vamos/')
from MyFunctions.misc_fun import *
from MyFunctions.GetGraph import *


# construct the argument parser and parse the arguments
ap = argparse.ArgumentParser()
ap.add_argument("-i", "--image", type=str, default='/Volumes/LaCie/ITKTubeTK/Normal002-MRA.mha',
	help="Input 3D image (stack) (.nrrd, .nii or .mha)")
ap.add_argument("-s", "--size", type=int, default=64,
	help="Crop size (in voxels)")

args = vars(ap.parse_args())

"""
inputpath = "RCAN_01_001_S_0.3.nrrd"
size = 64
Nb = 10
"""

inputpath = args["image"]
print('\ninputpath=\'%s\'' %(inputpath))
size = args["size"]
print('size=\'%d\'' %(size))


FileDir = os.path.dirname(os.path.abspath(inputpath)) + '/'
FileNameStack = (os.path.basename(inputpath))
FileName = os.path.splitext(os.path.basename(FileNameStack))[0]
fileext = os.path.splitext(inputpath)[1]

SaveDir = "_Crops/"
os.makedirs(os.path.dirname(SaveDir), exist_ok=True)


if fileext == '.nii' or fileext == '.mha' or fileext == '.nrrd':

	sitkimg = sitk.ReadImage(inputpath, sitk.sitkFloat32) #sitk.sitkUInt16)
	#spacing_or = sitkimg.GetSpacing()
	#sitkimg = resample_image(sitkimg, scale, is_label=False)
	#spacing = sitkimg.GetSpacing()
	stackGray = np.float32(sitk.GetArrayFromImage(sitkimg))

	segmName = FileDir + FileName + ".seg.nrrd"
	if os.path.isfile(segmName):
		SegmPath = segmName
	else:
		SegmPath = FileDir + 'Segmentation.seg.nrrd'

	sitkimgSegm = sitk.ReadImage(SegmPath)

	Arr = np.uint8(sitk.GetArrayFromImage(sitkimgSegm))
	"""
	if len(Arr.shape) > 3:
		ArrV = Arr[:,:,:,0]
		ArrA = Arr[:,:,:,1]
		Arr2 = np.zeros(ArrA.shape)
		Arr2[ArrV == 1] = 1
		Arr2[ArrA > 0] = ArrA[ArrA > 0]
		print("\nWARNING: dim > 3 !\n")
	else:
		Arr2 = Arr
	"""

	sitkimgSegm = sitk.GetImageFromArray(Arr)
	#sitkimgSegm.SetSpacing(spacing_or)
	#sitkimgSegm = resample_image(sitkimgSegm, scale, is_label=False)
	stackGraySegm = np.uint8(sitk.GetArrayFromImage(sitkimgSegm))

else:
	print("Please use nii or nrrd formats\n")
	sys.exit(0)

zs, ys, xs = stackGray.shape


NbICA = stackGraySegm.max()-1

"""
	Grab Ground Truth crops :
"""

for i in range(NbICA):

	ICA = np.copy(stackGraySegm)
	ICA[ICA != i+2] = 0
	ICA[ICA != 0] = 1

	Vascu = np.copy(stackGraySegm)
	Vascu[Vascu != 1] = 0

	"""
		Option #1 : place the crop center in the middle of the ICA neck.
	"""
	#DilatedICA = ndimage.binary_dilation(ICA).astype(ICA.dtype)	
	#Sum = DilatedICA + Vascu
	#pz,py,px = np.where(Sum == 2)
	#avZ = int(pz.mean())
	#avY = int(py.mean())
	#avX = int(px.mean())

	"""
		Option #2 : place the crop center at the center of the ICA.
	"""
	pz,py,px = np.where(ICA == 1)
	avZ = int(pz.mean())
	avY = int(py.mean())
	avX = int(px.mean())

	hs = int(size/2)
	GTCropImag = stackGray[avZ-hs:avZ+hs, avY-hs:avY+hs, avX-hs:avX+hs]
	GTCropSegm = stackGraySegm[avZ-hs:avZ+hs, avY-hs:avY+hs, avX-hs:avX+hs]

	sitk.WriteImage(sitk.GetImageFromArray(np.float32(GTCropImag)), SaveDir + FileName + '__ICA_' + str(i+1) + '.nrrd')
	sitk.WriteImage(sitk.GetImageFromArray(np.uint16(GTCropSegm)), SaveDir + FileName + '__ICA_' + str(i+1) + '.seg.nrrd')


