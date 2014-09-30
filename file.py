
import numpy as np
from axis import Axes

class File(object) :
	def __init__(self) :
		self.axes = Axes()
		self.variables = {}

	def __getattr__(self, attributeName) :
		if 'variables' in self.__dict__ :
			if attributeName in self.variables :
				return self.variables[attributeName]
		if 'axes' in self.__dict__ :
			return self.axes[attributeName]
		raise AttributeError
	
	def __getitem__(self, item) :
		return getattr(self, item)
	
	def close(self) :
		pass
	
	def write(self, filePath) :
		from netCDF4 import Dataset
		# making sure the variable's axes are given
		# to the file is the user's responsability
		with Dataset(filePath, 'w') as output :
			for axisName, axis in self.axes.iteritems() :
				output.createDimension(axisName, len(axis))
				if axisName == 'time' :
					output.createVariable('time', int, ('time',))
					output.variables['time'].units = 'seconds since 1970-1-1'
					from datetime import datetime
					epoch = datetime(1970, 1, 1)
					output.variables['time'][:] = [
						(instant-epoch).total_seconds()
						for instant in axis.data]
				else :
					output.createVariable(
							axisName, 
							type(np.asscalar(axis.data.ravel()[0])),
							(axisName,))
					output.variables[axisName][:] = axis.data
					# TODO metadata...
			for variableName, variable in self.variables.iteritems() :
				output.createVariable(
						variableName,
						type(np.asscalar(variable.data.ravel()[0])),
						tuple(variable.axes.keys()))
				output.variables[variableName][:] = variable.data
				# TODO metadata...

