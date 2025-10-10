from datetime import date, time, timedelta
from sqlalchemy import Interval, MetaData, Table, text, insert
from engine import create_engine
from enum import Enum, auto

class EntryParameterType(Enum):
    TITLE = auto()
    NOTES = auto()
    START_TIME = auto()
    DURATION = auto()

class EntryParameter():
    def __init__(self, parameter_type: EntryParameterType, parameter_value: str):
        self.parameter_type = parameter_type
        self.parameter_value = parameter_value
    
    '''
    validation based on the parameter_type
    '''
    def validate():
        return
    
'''
sql shortcut for logging a new entry and linking tags
input: all the necessary fields
output: should be true unless something goes horribly wrong. 
    data should be cleaned before it ever gets here. 
'''
def log_entry():
    return

'''
normalize tags into standardized format. stripped, lowercased, spaces instead of hyphens or underscores or anything.
'''
def normalize_tags():
    return


'''
main()
'''
if __name__ == '__main__':
    print("hello world")
    