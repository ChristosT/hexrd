import abc


class DistortionABC(metaclass=abc.ABCMeta):

    maptype = None

    @abc.abstractmethod
    def apply(self, xy_in):
        """Apply distortion mapping"""
        pass

    @abc.abstractmethod
    def apply_inverse(self, xy_in):
        """Apply inverse distortion mapping"""
        pass
