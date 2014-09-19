
import pygrib
import numpy as np
from operator import itemgetter
from os.path import splitext
from datetime import datetime
from datetime import timedelta

import aa


class File(aa.File) :
	def __init__(self, filePath) :
		super(File, self).__init__()
		fileName = splitext(filePath)[0]
		rawFile = pygrib.open(filePath)
		# read the first line of the file
		gribLine = rawFile.readline()
		firstInstant = datetime(gribLine.year, gribLine.month, gribLine.day,
					gribLine.hour, gribLine.minute, gribLine.second)
		###################
		# HORIZONTAL AXES #
		###################
		lats, lons = gribLine.latlons()
		if lats[0, 0] == lats[0, 1] :
			self.axes['latitude'] = aa.Axis(lats[:, 0], 'degrees')
			self.axes['longitude'] = aa.Parallel(lons[0, :], 'degrees')
		else :
			self.axes['latitude'] = aa.Axis(lats[0, :], 'degrees')
			self.axes['longitude'] = aa.Parallel(lons[:, 0], 'degrees')
		# give the lats to lon to get the proper weights
		self.axes['longitude'].latitudes = self.axes['latitude'].data
		#################
		# VERTICAL AXIS #
		#################
		# sometimes there are several types of level
		# 2D data is followed by 3D data e.g. jra25
		variablesLevels = {}					# variable - level type - level
		# loop through the variables and levels of the first time step
		while datetime(gribLine.year, gribLine.month, gribLine.day,
					gribLine.hour, gribLine.minute, gribLine.second)\
					== firstInstant :
			# is it the first time this variable is met ?
			if gribLine.shortName not in variablesLevels :
				# create a dictionary for that variable
				# that will contain different level types
				variablesLevels[gribLine.shortName] = {}
			# is this the first time this type of level is met ?
			if gribLine.typeOfLevel not in \
					variablesLevels[gribLine.shortName] :
					# create a list that will contain the level labels
				variablesLevels[gribLine.shortName][gribLine.typeOfLevel] = []
			# append the level label to the variable / level type
			variablesLevels[gribLine.shortName][gribLine.typeOfLevel]\
					.append(gribLine.level)
			# move to the next line
			gribLine = rawFile.readline()
		# find the longest vertical axis
		maxLevelNumber = 0
		for variableName, levelKinds in variablesLevels.iteritems() :
			for levelType, levels in levelKinds.iteritems() :
				# does levels look like a proper axis ?
				if len(levels) > 1 :
					variablesLevels[variableName][levelType] \
							= aa.Axis(np.array(levels), levelType)
				# is levels longer than the previous longest axis ?
				if len(levels) > maxLevelNumber :
					maxLevelNumber = len(levels)
					mainLevels = aa.Axis(np.array(levels), levelType)
		# the longest vertical axis gets to be the file's vertical axis
		self.axes['level'] = mainLevels
		#############
		# TIME AXIS #
		#############
		# "seek/tell" index starts with 1
		# but we've moved on the next instant at the end of the while loop
		# hence the minus one
		linesPerInstant = rawFile.tell() - 1
		# determine the interval between two samples
		secondInstant = datetime(gribLine.year, gribLine.month, gribLine.day,
					gribLine.hour, gribLine.minute, gribLine.second)
		timeStep = secondInstant - firstInstant
		# go to the end of the file
		rawFile.seek(0, 2)
		lastIndex = rawFile.tell()
		# this index points at the last message
		# e.g. f.message(lastIndex) returns the last message
		# indices start at 1 meaning that lastIndex is also the
		# number of messages in the file
		self.axes['time'] = aa.TimeAxis(
				np.array([firstInstant + timeIndex*timeStep
					for timeIndex in range(lastIndex/linesPerInstant)]),
				None)
		# check consistency
		gribLine = rawFile.message(lastIndex)
		lastInstant = datetime(gribLine.year, gribLine.month, gribLine.day,
					gribLine.hour, gribLine.minute, gribLine.second)
		if lastInstant != self.axes['time'][-1] or \
				lastIndex % linesPerInstant != 0 :
			print "Error in time axis"
		rawFile.rewind()
		#############
		# VARIABLES #
		#############
		for variableName, levelKinds in variablesLevels.iteritems() :
			for levelType, verticalAxis in levelKinds.iteritems() :
				conditions = {'shortName' : variableName.encode('ascii'),
						'typeOfLevel' : levelType.encode('ascii')}
				axes = aa.Axes()
				axes['time'] = self.axes['time']
				variableLabel = variableName + '_' + levelType
				# does this variable have a vertical extension ?
				# it may not be the file's vertical axis
				if len(verticalAxis) > 1 :
					axes['level'] = verticalAxis
					# in case of homonyms, only the variable with the main 
					# vertical axis gets to keep the original shortname
					if verticalAxis.units == mainLevels.units :
						variableLabel = variableName
				else :
					# flat level i.e. 2D data
					# the condition is a list to be iterable
					conditions['level'] = verticalAxis
				# no ambiguity
				if len(levelKinds) == 1 :
					variableLabel = variableName
				axes['latitude'] = self.axes['latitude']
				axes['longitude'] = self.axes['longitude']
				self.variables[variableLabel] = \
						Variable(axes, {}, conditions, fileName)
		##################
		# PICKLE & INDEX #
		##################
		rawFile.close()
		pickleFile = open(fileName+'.p', 'w')
		aa.pickle.dump(self, pickleFile)
		pickleFile.close()
		gribIndex = pygrib.index(filePath,
						'shortName', 'level', 'typeOfLevel',
						'year', 'month', 'day', 'hour')
		gribIndex.write(fileName+'.idx')
		gribIndex.close()	


class Variable(aa.Variable) :
	def __init__(self, axes, metadata, conditions, fileName) :
		super(Variable, self).__init__()
		self.axes = axes
		self.metadata = metadata
		self.conditions = conditions
		self.fileName = fileName
	
	def __call__(self, **kwargs) :
		"Extract a subset via its axes"
		# if the variable is still in pure grib mode
		if "_data" not in self.__dict__ :
			# conditions and axes of the output variable
			newConditions = self.conditions.copy()
			newAxes = self.axes.copy()
			for axisName, condition in kwargs.iteritems() :
				# standardize the axis name
				axisName = aa.Axes.aliases[axisName]
				# given the condition, call axis for a new version
				item, newAxis = self.axes[axisName](condition)
				# lat/lon get a special treatment within grib messages (array)
				if axisName in ['latitude', 'longitude'] :
					# already restrictions on lat/lon in the former conditions ?
					if axisName in self.conditions :
						# slices of slices not handled
						raise NotImplementedError
					else :
						newConditions[axisName] = item
				# time and level slices need to be made explicit
				else :
					# to what datetimes and pressures
					# do the conditions correspond ? slice former axis
					newConditions[axisName] = \
						self.axes[axisName][item]
					# make sure newConditions is still iterable though
					if not isinstance(newConditions[axisName], list) :
						newConditions[axisName] = \
							[newConditions[axisName]]
				# if item is scalar, there will be no need for an axis
				if newAxis == None :
					del newAxes[axisName]
				# otherwise, load newAxis in the new variable's axes
				else :
					newAxes[axisName] = newAxis
				if axisName == 'latitude' and 'longitude' in newAxes :
					newAxes['longitude'].latitudes = \
							self.axes['latitude'][newConditions['latitude']]\
							.reshape((-1,))
			return Variable(newAxes, self.metadata.copy(),
						newConditions, self.fileName)
		# if _data already exists (as a numpy array), follow standard protocol
		else :
			return super(Variable, self).__call__(**kwargs)
	
	def _get_data(self) :
		if '_data' not in self.__dict__ :
			# dummy conditions to play with
			newConditions = self.conditions.copy()
			# scalar conditions only (input for the gribIndex)
			subConditions = self.conditions.copy()
			################
			# TIME & LEVEL #
			################
			# assumes grib files always have a time dimension
			if 'time' not in self.conditions :
				newConditions['time'] = self.axes['time'].data
			else :
				# gribIndex won't want lists of datetimes
				# but rather individual year/month/day/hour
				del subConditions['time']
			# if data is 2D, it will have already have a level condition
			# idem if it's 3D and has already been sliced
			# if not, that means the user wants all available levels
			if 'level' not in self.conditions :
				newConditions['level'] = self.axes['level'].data
			########################
			# LATITUDE & LONGITUDE #
			########################
			### MASK ###
			# mask is used to slice the netcdf array contained in gribMessages
			mask = []
			if 'latitude' in self.conditions :
				del subConditions['latitude']
				mask.append(self.conditions['latitude'])
			else :
				mask.append(slice(None))
			twistedLongitudes = False
			if 'longitude' in self.conditions :
				del subConditions['longitude']
				# twisted longitudes...
				if type(self.conditions['longitude']) == tuple :
					twistedLongitudes = True
					secondMask = mask[:]
					mask.append(self.conditions['longitude'][0])
					slice1 = slice(0, -mask[-1].start)
					secondMask.append(self.conditions['longitude'][1])
					slice2 = slice(-secondMask[-1].stop, None)
				else :
					mask.append(self.conditions['longitude'])
			else :
				mask.append(slice(None))
			mask = tuple(mask)
			### HORIZONTAL SHAPE ###
			# shape of the output array : (time, level, horizontalShape)
			horizontalShape = []
			if hasattr(self, 'lats') :
				horizontalShape.append(len(self.lats))
			if hasattr(self, 'lons') :
				horizontalShape.append(len(self.lons))
			horizontalShape = tuple(horizontalShape)
			#####################
			# GET GRIB MESSAGES #
			#####################
			shape = ()
			for axisName, axis in self.axes.iteritems() :
				shape = shape + (len(axis),)
			# build the output numpy array
			self._data = np.empty(shape, dtype=float)
			# flatten time and level dimensions
			# that's in case there's neither time nor level dimension
			self._data.shape = (-1,) + horizontalShape
			# load the grib index
			gribIndex = pygrib.index(self.fileName+'.idx')
			lineIndex = 0
			for instant in newConditions['time'] :
				subConditions['year'] = instant.year
				subConditions['month'] = instant.month
				subConditions['day'] = instant.day
				subConditions['hour'] = instant.hour
				for level in newConditions['level'] :
					subConditions['level'] = \
						np.asscalar(np.array(level))
						# converts numpy types to standard types
						# standard types are converted to numpy
					# normally, there should be only one line
					# that answers our query
					gribLine = gribIndex(**subConditions)[0]
					if twistedLongitudes :
						self._data[lineIndex, ..., slice1] = \
							gribLine.values[mask]
						self._data[lineIndex, ..., slice2] = \
							gribLine.values[secondMask]
					else :
						self._data[lineIndex] = gribLine.values[mask]
					lineIndex += 1
			gribIndex.close()
			self._data.shape = shape
		return self._data
	def _set_data(self, newValue) :
		self._data = newValue
	data = property(_get_data, _set_data)

