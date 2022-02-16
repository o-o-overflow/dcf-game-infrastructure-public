import string

class Config(object):
    FLAG_PREFIX="000"
    FLAG_ALPHABET='ABCDEF'  + string.digits
    FLAG_LENGTH=48 - len(FLAG_PREFIX)
    FLAG_SUFFIX=""
    # https://stackoverflow.com/questions/33738467/how-do-i-know-if-i-can-disable-sqlalchemy-track-modifications/33790196#33790196
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER="./uploads"
    RQ_ASYNC=True
    RQ_REDIS_URL='redis://redis/'
