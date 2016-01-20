from __future__ import division

import os.path

import numpy as np
import scipy.io.wavfile as wav

from WindowType import WindowType
import FftUtils
import Constants


class AudioSignal(object):
    """Defines properties of an audio signal and performs basic operations such as Wav loading and STFT/iSTFT.

    Parameters:
        pathToInputFile (string): string specifying path to file. Either this or timeSeries must be provided
        timeSeries (np.array): Numpy matrix containing a time series of a signal
        signalStartingPosition (Optional[int]): Starting point of the section to be extracted in seconds. Defaults to 0
        signalLength (Optional[int]): Length of the signal to be extracted. Defaults to full length of the signal
        SampleRate (Optional[int]): sampling rate to read audio file at. Defaults to Constants.DEFAULT_SAMPLE_RATE
        stft (Optional[np.array]): Optional pre-coumputed complex spectrogram data.

    Attributes:
        windowType(WindowType): type of window to use in operations on the signal. Defaults to WindowType.DEFAULT
        windowLength (int): Length of window in ms. Defaults to 0.06 * SampleRate
        nfft (int): Number of samples for fft. Defaults to windowLength
        overlapRatio (float): Ratio of window that overlaps in [0,1). Defaults to 0.5
        ComplexSpectrogramData (np.array): complex spectrogram of the data
        PowerSpectrogramData (np.array): power spectrogram of the data
        Fvec (np.array): frequency vector for stft
        Tvec (np.array): time vector for stft
        SampleRate (ReadOnly[int]): sampling frequency
  
    Examples:
        * create a new signal object:     ``sig=AudioSignal('sample_audio_file.wav')``
        * compute the spectrogram of the new signal object:   ``sigSpec,sigPow,F,T=sig.STFT()``
        * compute the inverse stft of a spectrogram:          ``sigrec,tvec=sig.iSTFT()``
  
    """

    def __init__(self, pathToInputFile=None, timeSeries=None, signalStartingPosition=0, signalLength=0,
                 sampleRate=Constants.DEFAULT_SAMPLE_RATE, stft=None):

        self.PathToInputFile = pathToInputFile
        self._audioData = None
        self.time = np.array([])
        #self.SignalLength = signalLength
        #self.nChannels = 1
        self.SampleRate = sampleRate

        if (pathToInputFile is not None) and (timeSeries is not None):
            raise Exception('Cannot initialize AudioSignal object with a path AND an array!')

        if pathToInputFile is not None:
            self.LoadAudioFromFile(self.PathToInputFile, signalLength, signalStartingPosition)
        elif timeSeries is not None:
            self.LoadAudioFromArray(timeSeries, sampleRate)

        # STFT properties
        self.ComplexSpectrogramData = np.array([]) if stft is None else stft  # complex spectrogram
        self.PowerSpectrumData = np.array([])  # power spectrogram
        self.Fvec = np.array([])  # freq. vector
        self.Tvec = np.array([])  # time vector

        # TODO: put these in a WindowAttributes object and wrap in a property
        self.windowType = WindowType.DEFAULT
        self.windowLength = int(0.06 * self.SampleRate)
        self.nfft = self.windowLength
        self.overlapRatio = 0.5
        self.overlapSamp = int(np.ceil(self.overlapRatio * self.windowLength))
        self.FrequencyMaxPlot = self.SampleRate / 2

    ##################################################
    # Properties
    ##################################################

    # Constants for accessing _audioData np.array indices
    _LEN = 1
    _CHAN = 0

    @property
    def SignalLength(self):
        """int: Length of the audio signal
        """
        return self._audioData.shape[self._LEN]

    @property
    def nChannels(self):
        """int: Number of channels
        """
        return self._audioData.shape[self._CHAN]

    @property
    def AudioData(self):
        """np.array: Array containing audio data
        """
        return self._audioData

    @AudioData.setter
    def AudioData(self, value):
        assert (type(value) == np.ndarray)

        self._audioData = value

        if self._audioData.ndim < 2:
            self._audioData = np.expand_dims(self._audioData, axis=self._CHAN)

    @property
    def FileName(self):
        """ Filename of audio file on disk
        """
        if self.PathToInputFile is not None:
            return os.path.split(self.PathToInputFile)[1]
        return None


    ##################################################
    # I/O
    ##################################################

    def LoadAudioFromFile(self, inputFileName, signalStartingPosition=0, signalLength=0):
        """Loads an audio signal from a .wav file

        Parameters:
            inputFileName (str): String to audio file to load
            signalStartingPosition (Optional[int]): Starting point of the section to be extracted. Defaults to 0 seconds
            signalLength (Optional[int]): Length of the signal to be extracted. Defaults to 0 seconds
        
        """
        try:
            self.SampleRate, audioInput = wav.read(inputFileName)
        except Exception, e:
            print "Cannot read from file, {file}".format(file=inputFileName)
            raise e

        audioInput = audioInput.T

        # Change from fixed point to floating point
        audioInput = audioInput.astype('float') / (np.iinfo(audioInput.dtype).max + 1.0)

        # TODO: the logic here needs work
        if signalLength == 0:
            self.AudioData = np.array(audioInput)
        else:
            startPos = int(signalStartingPosition * self.SampleRate)
            self.AudioData = np.array(audioInput[startPos: startPos + self.SignalLength, :])

        self.time = np.array((1. / self.SampleRate) * np.arange(self.SignalLength))

    def LoadAudioFromArray(self, signal, sampleRate=Constants.DEFAULT_SAMPLE_RATE):
        """Loads an audio signal from a numpy array

        Parameters:
            signal (np.array): np.array containing the audio file signal sampled at sampleRate
            sampleRate (Optional[int]): the sampleRate of signal. Default is Constants.DEFAULT_SAMPLE_RATE

        """
        self.PathToInputFile = None
        self.AudioData = np.array(signal)
        self.SampleRate = sampleRate

        self.time = np.array((1. / self.SampleRate) * np.arange(self.SignalLength))

    # TODO: verbose toggle
    def WriteAudioFile(self, outputFileName, sampleRate=None, verbose=False):
        """records the audio signal to a .wav file

        Parameters:
            outputFileName (str): Filename where waveform will be saved
            sampleRate (Optional[int]): The sample rate to write the file at. Default is AudioSignal.SampleRate, which
            is the samplerate of the original signal.
            verbose (Optioanl[bool]): Flag controlling printing when writing the file.
        """
        if self.AudioData is None:
            raise Exception("Cannot write audio file because there is no audio data.")

        try:
            self.PeakNormalize()

            if sampleRate is None:
                sampleRate = self.SampleRate

            wav.write(outputFileName, sampleRate, self.AudioData.T)
        except Exception, e:
            print "Cannot write to file, {file}.".format(file=outputFileName)
            raise e
        if verbose:
            print "Successfully wrote {file}.".format(file=outputFileName)

    ##################################################
    #               STFT Utilities
    ##################################################

    def STFT(self):
        """computes the STFT of the audio signal

        Returns:
            * **ComplexSpectrogramData** (*np.array*) - complex stft data

            * **PowerSpectrumData** (*np.array*) - power spectrogram

            * **Fvec** (*np.array*) - frequency vector

            * **Tvec** (*np.array*) - vector of time frames

        """
        if self.AudioData is None:
            raise Exception("No audio data to make STFT from.")

        for i in range(1, self.nChannels + 1):
            Xtemp, Ptemp, Ftemp, Ttemp = FftUtils.f_stft(self.getChannel(i).T, nFfts=self.nfft,
                                                         winLength=self.windowLength, windowType=self.windowType,
                                                         winOverlap=self.overlapSamp, sampleRate=self.SampleRate,
                                                         mkplot=0)

            if np.size(self.ComplexSpectrogramData) == 0:
                self.ComplexSpectrogramData = Xtemp
                self.PowerSpectrumData = Ptemp
                self.Fvec = Ftemp
                self.Tvec = Ttemp
            else:
                self.ComplexSpectrogramData = np.dstack([self.ComplexSpectrogramData, Xtemp])
                self.PowerSpectrumData = np.dstack([self.PowerSpectrumData, Ptemp])

        return self.ComplexSpectrogramData, self.PowerSpectrumData, self.Fvec, self.Tvec

    def iSTFT(self):
        """Computes and returns the inverse STFT.

        Warning:
            Will overwrite any data in self.AudioData!

        Returns:
             AudioData (np.array): time-domain signal
             time (np.array): time vector
        """
        if self.ComplexSpectrogramData.size == 0:
            raise Exception('Cannot do inverse STFT without STFT data!')

        self.AudioData = np.array([])
        for i in range(1, self.nChannels + 1):
            x_temp, t_temp = FftUtils.f_istft(self.ComplexSpectrogramData, self.windowLength,
                                              self.windowType,
                                              self.overlapSamp, self.SampleRate)

            if np.size(self.AudioData) == 0:
                self.AudioData = np.array(x_temp).T
                self.time = np.array(t_temp).T
            else:
                self.AudioData = np.hstack([self.AudioData, np.array(x_temp).T])

        if len(self.AudioData.shape) == 1:
            self.AudioData = np.expand_dims(self.AudioData, axis=1)

        return self.AudioData, self.time

    ##################################################
    #                  Utilities
    ##################################################

    def concat(self, other):
        """ concatenates two AudioSignals and puts them in AudioData

        Parameters:
            other (AudioSignal): Audio Signal to concatenate with the current one.
        """
        if self.nChannels != other.nChannels:
            raise Exception('Cannot concat two signals that have a different number of channels!')

        self.AudioData = np.concatenate((self.AudioData, other.AudioData))

    def getChannel(self, n):
        """Gets the n-th channel. 1-based.

        Parameters:
            n (int): index of channel to get 1-based.
        Returns:
             n-th channel (np.array): the data in the n-th channel of the signal
        """
        return self.AudioData[n - 1,]

    def PeakNormalize(self, bitDepth=16):
        """Normalizes the whole audio file to the max value.

        Parameters:
            bitDepth (Optional[int]): Max value (in bits) to normalize to. Default is 16 bits.
        """
        bitDepth -= 1
        maxVal = 1.0
        maxSignal = np.max(np.abs(self.AudioData))
        if maxSignal > maxVal:
            self.AudioData = np.divide(self.AudioData, maxSignal)

    ##################################################
    #              Operator overloading
    ##################################################

    def __add__(self, other):
        if self.nChannels != other.nChannels:
            raise Exception('Cannot add two signals that have a different number of channels!')

        # for ch in range(self.nChannels):
        # TODO: make this work for multiple channels
        if self.AudioData.size > other.AudioData.size:
            combined = np.copy(self.AudioData)
            combined[0: other.AudioData.size] += other.AudioData
        else:
            combined = np.copy(other.AudioData)
            combined[0: self.AudioData.size] += self.AudioData

        return AudioSignal(timeSeries=combined)

    def __sub__(self, other):
        if self.nChannels != other.nChannels:
            raise Exception('Cannot subtract two signals that have a different number of channels!')

        # for ch in range(self.nChannels):
        # TODO: make this work for multiple channels
        if self.AudioData.size > other.AudioData.size:
            combined = np.copy(self.AudioData)
            combined[0: other.AudioData.size] -= other.AudioData
        else:
            combined = np.copy(other.AudioData)
            combined[0: self.AudioData.size] -= self.AudioData

        return AudioSignal(timeSeries=combined)

    def __iadd__(self, other):
        return self + other

    def __isub__(self, other):
        return self - other

    def __len__(self):
        return len(self.AudioData)

