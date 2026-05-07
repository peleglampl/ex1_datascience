import logging
import os
import sys

def setup_logger(name='book_crawler', log_file='app.log', level=logging.DEBUG):
    """Function to setup a professional logger with file and console handlers"""
    
    # Use the root directory for the log file
    log_path = os.path.join(os.getcwd(), log_file)

    # Professional format including timestamp, logger name, level, and message
    # Adding line number and filename for easier debugging of the "hanging" bug
    formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s')

    # File handler (RotatingFileHandler is better for production, but simple FileHandler for now)
    try:
        file_handler = logging.FileHandler(log_path, encoding='utf-8', mode='a')
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
    except Exception as e:
        print(f"Failed to initialize file handler: {e}")
        file_handler = None

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO) # Keep console clean with INFO

    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    if file_handler:
        logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Prevent logs from propagating to the root logger twice
    logger.propagate = False

    return logger

# Initialize a default logger
logger = setup_logger()
