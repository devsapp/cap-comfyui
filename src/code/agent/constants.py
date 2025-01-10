import os

WORK_DIR = os.getenv('WORK_DIR', '/root')
MNT_DIR = os.getenv('MNT_DIR')
if MNT_DIR is None:
    raise ValueError("Environment variable 'MNT_DIR' is not set")
SNAPSHOT_DIR = MNT_DIR + '/snapshots'
SNAPSHOT_PATTERN = '%Y%m%d-%H%M%S'
