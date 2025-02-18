import logging

def setup_logger(name: str) -> logging.Logger:
    """Logger kurulumu"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Handler
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    
    # Add handler to logger
    logger.addHandler(handler)
    
    return logger 