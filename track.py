class Track:
    def __init__(self,name):
        self.name = name
        self.file_path = None
        self.volime = 1.0
        self.muted = False

    def load(self, path):
        self.file_path = path    