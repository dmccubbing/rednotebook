#!/usr/bin/env python
# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------
# Copyright (c) 2009  Jendrik Seipp
# 
# RedNotebook is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
# 
# RedNotebook is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License along
# with RedNotebook; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
# -----------------------------------------------------------------------

from __future__ import with_statement

import sys
import datetime
import os
import zipfile
import operator


if hasattr(sys, "frozen"):
	#TODO:
	from rednotebook.util import filesystem
	from rednotebook.util import utils
else:
	from util import filesystem # creates a copy of filesystem module
	#import util.filesystem # imports the original filesystem module
	from util import utils

## Enable logging
import logging
loggingLevels = {'debug': logging.DEBUG,
				'info': logging.INFO,
				'warning': logging.WARNING,
				'error': logging.ERROR,
				'critical': logging.CRITICAL}

# File logging
if sys.platform == 'win32':
	if hasattr(sys, "frozen"):
		utils.redirect_output_to_file()
else:
	logging.basicConfig(level=logging.DEBUG,
	                    format='%(asctime)s %(levelname)-8s %(message)s',
	                    filename=filesystem.logFile,
	                    filemode='w',
	                    #stream=sys.stdout,
	                    )

level = logging.INFO
if len(sys.argv) > 1:
	level = loggingLevels.get(sys.argv[1], level)

# define a Handler which writes INFO messages or higher to the sys.stderr
console = logging.StreamHandler()
console.setLevel(level)
# set a format which is simpler for console use
formatter = logging.Formatter('%(levelname)-8s %(message)s')
# tell the handler to use this format
console.setFormatter(formatter)
# add the handler to the root logger
logging.getLogger('').addHandler(console)


try:
	import pygtk
except ImportError:
	utils.printError('Please install PyGTK (python-gtk2)')
	sys.exit(1)

pygtk.require("2.0")

try:
	import gtk
	import gobject
except (ImportError, AssertionError):
	utils.printError('Please install PyGTK (python-gtk2)')
	sys.exit(1)

try:
	import yaml
except ImportError:
	utils.printError('Yaml is not installed (install python-yaml)')
	sys.exit(1)

	

logging.info('AppDir: %s' % filesystem.appDir)
baseDir = os.path.abspath(os.path.join(filesystem.appDir, '../'))
logging.info('BaseDir: %s' % baseDir)
if baseDir not in sys.path:
	logging.info('Adding BaseDir to sys.path')
	sys.path.insert(0, baseDir)
	



# This version of import is needed for win32 to work
from rednotebook.util import unicode
from rednotebook.util import dates
from rednotebook import info
from rednotebook import config
from rednotebook import backup

from rednotebook.gui.mainWindow import MainWindow
from rednotebook.util.statistics import Statistics



class RedNotebook:
	
	def __init__(self):
		self.testing = False
		if 'debug' in sys.argv:
			self.testing = True
			logging.debug('Debug Mode is on')
		
		self.month = None
		self.date = None
		self.months = {}
		
		# The dir name is the title
		self.title = ''
		
		self.dirs = filesystem.Filenames()
		
		# show instructions at first start or if testing
		self.firstTimeExecution = not os.path.exists(self.dirs.dataDir)
		logging.info('First Start: %s' % self.firstTimeExecution)
		
		logging.info('RedNotebook version: %s' % info.version)
		logging.info(filesystem.get_platform_info())
		
		filesystem.makeDirectories([filesystem.redNotebookUserDir, self.dirs.dataDir, \
								filesystem.templateDir, filesystem.tempDir])
		filesystem.makeFiles([(filesystem.configFile, ''),
								(filesystem.logFile, '')])
		
		self.config = config.Config()
		
		utils.set_environment_variables(self.config)
		
		# Let components check if the MainWindow has been created
		self.frame = None
		self.frame = MainWindow(self)
		   
		self.actualDate = datetime.date.today()
		
		self.dirs.dataDir = self.config.read('dataDir', self.dirs.dataDir)
		
		if self.testing:
			self.dirs.dataDir = os.path.join(filesystem.redNotebookUserDir, "data-test/")
			filesystem.makeDirectory(self.dirs.dataDir)
		# HACK: Only load test dir with active debug option
		elif self.dirs.dataDir == os.path.join(filesystem.redNotebookUserDir, "data-test/"):
			self.dirs.dataDir = filesystem.defaultDataDir
			
		self.open_journal(self.dirs.dataDir)
		
		self.archiver = backup.Archiver(self)
		
		# Check for a new version
		if self.config.read('checkForNewVersion', default=0) == 1:
			utils.check_new_version(self.frame, info.version, startup=True)
			
		# Automatically save the content after a period of time
		one_minute = 1000 * 60
		
		if not self.testing:
			gobject.timeout_add(10 * one_minute, self.saveToDisk)
	
	
	def getDaysInDateRange(self, range):
		startDate, endDate = range
		assert startDate <= endDate
		
		sortedDays = self.sortedDays
		daysInDateRange = []
		for day in sortedDays:
			if day.date < startDate:
				continue
			elif day.date >= startDate and day.date <= endDate:
				daysInDateRange.append(day)
			elif day.date > endDate:
				break
		return daysInDateRange
		
		
	def _getSortedDays(self):
		return sorted(self.days, key=lambda day: day.date)
	sortedDays = property(_getSortedDays)
	
	
	def getEditDateOfEntryNumber(self, entryNumber):
		sortedDays = self.sortedDays
		if len(self.sortedDays) == 0:
			return datetime.date.today()
		return self.sortedDays[entryNumber % len(sortedDays)].date
	
	
	def backupContents(self, backup_file):
		self.saveToDisk()
		
		if backup_file:
			self.archiver.backup(backup_file)

	
	def saveToDisk(self, exitImminent=False, changing_journal=False):
		self.saveOldDay()
		
		filesystem.makeDirectories([filesystem.redNotebookUserDir, self.dirs.dataDir,])
		
		for yearAndMonth, month in self.months.items():
			if not month.empty and month.visited:
				monthFileString = os.path.join(self.dirs.dataDir, yearAndMonth + \
											filesystem.fileNameExtension)
				with open(monthFileString, 'w') as monthFile:
					monthContent = {}
					for dayNumber, day in month.days.iteritems():
						# do not add empty days
						if not day.empty:
							monthContent[dayNumber] = day.content
					#month.prettyPrint()
					yaml.dump(monthContent, monthFile)
		
		self.showMessage('The content has been saved to %s' % self.dirs.dataDir, error=False)
		
		self.config.saveToDisk()
		
		if not (exitImminent or changing_journal):
			# Update cloud
			self.frame.cloud.update(force_update=True)
			
		# tell gobject to keep saving the content in regular intervals
		return True
	
	
	def open_journal(self, data_dir, load_files=True):
		
		if self.months:
			self.saveToDisk(changing_journal=True)
		
		logging.info('Opening journal at %s' % data_dir)
		
		if not os.path.exists(data_dir):
			logging.warning('The data dir %s does not exist. Select a different dir.' \
						% data_dir)
			
			self.frame.show_dir_chooser('open')
			return
			# Just to be sure
			#filesystem.makeDirectory(self.dirs.defaultDataDir)
			
			#data_dir = self.dirs.defaultDataDir
			#logging.info('Opening journal at %s' % data_dir)
		
		data_dir_empty = not os.listdir(data_dir)
		
		if not load_files and not data_dir_empty:
			self.showMessage('The selected folder is not empty. To prevent ' + \
							'you from overwriting data, the content has been ' + \
							'imported into the new journal.', error=False)
		elif load_files and data_dir_empty:
			self.showMessage('The selected folder is empty. A new journal ' + \
							'has been created.', error=False)
		
		self.dirs.dataDir = data_dir
		
		self.month = None
		self.months.clear()
		
		# We always want to load all files
		if load_files or True:
			self.loadAllMonthsFromDisk()
		
		# Nothing to save before first day change
		self.loadDay(self.actualDate)
		
		self.stats = Statistics(self)
		
		sortedCategories = sorted(self.nodeNames, key=lambda category: str(category).lower())
		self.frame.categoriesTreeView.categories = sortedCategories
		
		if self.firstTimeExecution is True:
			self.addInstructionContent()
			
		# Show cloud tab, cloud is updated automatically
		self.frame.searchNotebook.set_current_page(1)
		
		# Reset Search
		self.frame.searchBox.clear()
		
		self.title = filesystem.get_journal_title(data_dir)
		
		# Set frame title
		if self.title == 'data':
			frame_title = 'RedNotebook'
		else:
			frame_title = 'RedNotebook - ' + self.title
		self.frame.mainFrame.set_title(frame_title)
		
		# Save the folder for next start
		self.config['dataDir'] = data_dir
		
		
		
	def loadAllMonthsFromDisk(self):
		for root, dirs, files in os.walk(self.dirs.dataDir):
			for file in files:
				self.loadMonthFromDisk(os.path.join(root, file))
	
	
	def loadMonthFromDisk(self, path):
		# path: /something/somewhere/2009-01.txt
		# fileName: 2009-01.txt
		fileName = os.path.basename(path)
		
		try:
			# Get Year and Month from filename
			yearAndMonth, extension = os.path.splitext(fileName)
			yearNumber, monthNumber = yearAndMonth.split('-')
			yearNumber = int(yearNumber)
			monthNumber = int(monthNumber)
			assert monthNumber in range(1,13)
		except Exception:
			msg = '''Error: %s is an incorrect filename. \
Filenames have to have the following form: 2009-01.txt \
'for January 2009 (yearWith4Digits-monthWith2Digits.txt)''' % fileName
			logging.error(msg)
			return
		
		monthFileString = path
		
		try:
			# Try to read the contents of the file
			with open(monthFileString, 'r') as monthFile:
				monthContents = yaml.load(monthFile)
				self.months[yearAndMonth] = Month(yearNumber, monthNumber, monthContents)
		except yaml.YAMLError, exc:
			logging.error('Error in file %s:\n%s' % (monthFileString, exc))
		except IOError:
			#If that fails, there is nothing to load, so just display an error message
			logging.error('Error: The file %s could not be read' % monthFileString)
		except Exception:
			logging.error('An error occured while reading %s' % monthFileString)
		
		
	def loadMonth(self, date):
		
		yearAndMonth = dates.getYearAndMonthFromDate(date)
		
		'Selected month has not been loaded or created yet'
		if not self.months.has_key(yearAndMonth):
			self.months[yearAndMonth] = Month(date.year, date.month)
			
		return self.months[yearAndMonth]
	
	
	def saveOldDay(self):
		'Order is important'
		self.day.content = self.frame.categoriesTreeView.get_day_content()
		
		self.day.text = self.frame.get_day_text()
		self.frame.calendar.setDayEdited(self.date.day, not self.day.empty)
	
	
	def loadDay(self, newDate):
		oldDate = self.date
		self.date = newDate
		
		if not Month.sameMonth(newDate, oldDate) or self.month is None:
			self.month = self.loadMonth(self.date)
			self.month.visited = True
		self.frame.set_date(self.month, self.date, self.day)
		
		
	def _getCurrentDay(self):
		return self.month.getDay(self.date.day)
	day = property(_getCurrentDay)
	
	
	def changeDate(self, newDate):
		if newDate == self.date:
			return
		
		self.saveOldDay()
		self.loadDay(newDate)
		
		
	def goToNextDay(self):
		self.changeDate(self.date + dates.oneDay)
		
		
	def goToPrevDay(self):
		self.changeDate(self.date - dates.oneDay)
			
			
	def showMessage(self, messageText, error=False, countdown=True):
		self.frame.statusbar.showText(messageText, error, countdown)
		logging.info(messageText)
		
		
	def _getNodeNames(self):
		nodeNames = set([])
		for month in self.months.values():
			nodeNames |= set(month.nodeNames)
		return list(nodeNames)
	nodeNames = property(_getNodeNames)
	
	
	def _getTags(self):
		tags = set([])
		for month in self.months.values():
			tags |= set(month.tags)
		return list(tags)
	tags = property(_getTags)
	
	
	def search(self, text=None, category=None, tag=None):
		results = []
		for day in self.days:
			result = None
			if text:
				result = day.search_text(text)
			elif category:
				result = day.search_category(category)
			elif tag:
				result = day.search_tag(tag)
			
			if result:
				if category:
					results.extend(result)
				else:
					results.append(result)
					
		return results
	
	
	def _getAllEditedDays(self):
		days = []
		for month in self.months.values():
			daysInMonth = month.days.values()
			
			'Filter out days without content'
			daysInMonth = filter(lambda day: not day.empty, daysInMonth)
			days.extend(daysInMonth)
		return days
	days = property(_getAllEditedDays)
	
	
	def getWordCountDict(self, type):
		'''
		Returns a dictionary mapping the words to their number of appearance
		'''
		wordDict = utils.ZeroBasedDict()
		for day in self.days:
			if type == 'word':
				words = day.words
			if type == 'category':
				words = day.nodeNames
			if type == 'tag':
				words = day.tags
			
			for word in words:
				wordDict[word.lower()] += 1
		return wordDict
			
	
	def addInstructionContent(self):
		instructionDayContent = {u'Cool Stuff': {u'Went to see the pope': None}, 
								 u'Ideas': {u'Invent Anti-Hangover-Machine': None},
								 u'Tags': {u'Work': None, u'Projects': None},
								 }
		
		self.day.content = instructionDayContent
		self.day.text = info.completeWelcomeText
		
		self.frame.set_date(self.month, self.date, self.day)

			

class Day(object):
	def __init__(self, month, dayNumber, dayContent = None):
		if dayContent == None:
			dayContent = {}
			
		self.date = datetime.date(month.yearNumber, month.monthNumber, dayNumber)
			
		self.month = month
		self.dayNumber = dayNumber
		self.content = dayContent
		
		self.searchResultLength = 50
		
	def __getattr__(self, name):
		return getattr(self.date, name)
	
	
	'Text'
	def _getText(self):
		if self.content.has_key('text'):
			return self.content['text']
		else:
		   return ''
		
	def _setText(self, text):
		self.content['text'] = text
	text = property(_getText, _setText)
	
	def _hasText(self):
		return len(self.text.strip()) > 0
	hasText = property(_hasText)
	
	
	def _isEmpty(self):
		if len(self.content.keys()) == 0:
			return True
		elif len(self.content.keys()) == 1 and self.content.has_key('text') and not self.hasText:
			return True
		else:
			return False
	empty = property(_isEmpty)
		
		
	def _getTree(self):
		tree = self.content.copy()
		if tree.has_key('text'):
			del tree['text']
		return tree
	tree = property(_getTree)
	
	
	def _getNodeNames(self):
		return self.tree.keys()
	nodeNames = property(_getNodeNames)
		
		
	def _getTags(self):
		tags = []
		for category, listContent in self.getCategoryContentPairs().iteritems():
			if category.upper() == 'TAGS':
				tags.extend(listContent)
		return set(tags)
	tags = property(_getTags)
	
	
	def getCategoryContentPairs(self):
		'''
		Returns a list of (category, contentInCategoryAsList) pairs.
		contentInCategoryAsList can be empty
		'''
		originalTree = self.tree.copy()
		pairs = {}
		for category, content in originalTree.iteritems():
			entryList = []
			if content is not None:
				for entry, nonetype in content.iteritems():
					entryList.append(entry)
			pairs[category] = entryList
		return pairs
	
	
	def _getWords(self, withSpecialChars=False):
		if withSpecialChars:
			return self.text.split()
		
		wordList = self.text.split()
		realWords = []
		for word in wordList:
			word = word.strip(u'.|-!"/()=?*+~#_:;,<>^°´`{}[]')
			if len(word) > 0:
				realWords.append(word)
		return realWords
	words = property(_getWords)
	
	
	def getNumberOfWords(self):
		return len(self._getWords(withSpecialChars=True))
	
	
	def search_text(self, searchText):
		'''Case-insensitive search'''
		upCaseSearchText = searchText.upper()
		upCaseDayText = self.text.upper()
		occurence = upCaseDayText.find(upCaseSearchText)
		
		if occurence > -1:
			'searchText is in text'
			
			searchedStringInText = self.text[occurence:occurence + len(searchText)]
			
			spaceSearchLeftStart = max(0, occurence - self.searchResultLength/2)
			spaceSearchRightEnd = min(len(self.text), \
									occurence + len(searchText) + self.searchResultLength/2)
				
			resultTextStart = self.text.find(' ', spaceSearchLeftStart, occurence)
			resultTextEnd = self.text.rfind(' ', occurence + len(searchText), spaceSearchRightEnd)
			if resultTextStart == -1:
				resultTextStart = occurence - self.searchResultLength/2
			if resultTextEnd == -1:
				resultTextEnd = occurence + len(searchText) + self.searchResultLength/2
				
			'Add leading and trailing ... if appropriate'
			resultText = ''
			if resultTextStart > 0:
				resultText += '... '
				
			resultText += unicode.substring(self.text, resultTextStart, resultTextEnd).strip()
			
			'Make the searchedText bold'
			resultText = resultText.replace(searchedStringInText, '<b>' + searchedStringInText + '</b>')
			
			if resultTextEnd < len(self.text) - 1:
				resultText += ' ...'
				
			'Delete newlines'
			resultText = resultText.replace('\n', '')
				
			return (str(self), resultText)
		else:
			return None
		
		
	def search_category(self, searchCategory):
		results = []
		for category, content in self.getCategoryContentPairs().iteritems():
			if content:
				if searchCategory.upper() in category.upper():
					for entry in content:
						results.append((str(self), entry))
		return results
	
	
	def search_tag(self, searchTag):
		for category, contentList in self.getCategoryContentPairs().iteritems():
			if category.upper() == 'TAGS' and contentList:
				if searchTag.upper() in map(lambda x: x.upper(), contentList):
					firstWhitespace = self.text.find(' ', self.searchResultLength)
					
					if firstWhitespace == -1:
						'No whitespace found'
						textStart = self.text
					else:
						textStart = self.text[:firstWhitespace + 1]
						
					textStart = textStart.replace('\n', '')
					
					if len(textStart) < len(self.text):
						textStart += ' ...'
					return (str(self), textStart)
		return None
	
	
	def __str__(self):
		dayNumberString = str(self.dayNumber).zfill(2)
		monthNumberString = str(self.month.monthNumber).zfill(2)
		yearNumberString = str(self.month.yearNumber)
			
		return yearNumberString + '-' + monthNumberString + '-' + dayNumberString

			

class Month(object):
	def __init__(self, yearNumber, monthNumber, monthContent = None):
		if monthContent == None:
			monthContent = {}
		
		self.yearNumber = yearNumber
		self.monthNumber = monthNumber
		self.days = {}
		for dayNumber, dayContent in monthContent.iteritems():
			self.days[dayNumber] = Day(self, dayNumber, dayContent)
			
		self.visited = False
	
	
	def getDay(self, dayNumber):
		if self.days.has_key(dayNumber):
			return self.days[dayNumber]
		else:
			newDay = Day(self, dayNumber)
			self.days[dayNumber] = newDay
			return newDay
		
		
	def setDay(self, dayNumber, day):
		self.days[dayNumber] = day
		
		
	def prettyPrint(self):
		print '***'
		for dayNumber, day in self.days.iteritems():
			print dayNumber, 
			unicode.printUnicode(day.text)
		print '---'
		
		
	def _isEmpty(self):
		for day in self.days.values():
			if not day.empty:
				return False
		return True
	empty = property(_isEmpty)
	
	
	def _getNodeNames(self):
		nodeNames = set([])
		for day in self.days.values():
			nodeNames |= set(day.nodeNames)
		return nodeNames
	nodeNames = property(_getNodeNames)
	
	
	def _getTags(self):
		tags = set([])
		for day in self.days.values():
			tags |= set(day.tags)
		return tags
	tags = property(_getTags)
	
	
	def sameMonth(date1, date2):
		if date1 == None or date2 == None:
			return False
		return date1.month == date2.month and date1.year == date2.year
	sameMonth = staticmethod(sameMonth)
		
	
	
def main():
	redNotebook = RedNotebook()
	utils.setup_signal_handlers(redNotebook)
	
	try:
		gtk.main()
	except KeyboardInterrupt:
		#print 'Interrupt'
		#redNotebook.saveToDisk()
		sys.exit()
		

if __name__ == '__main__':
	main()
	
