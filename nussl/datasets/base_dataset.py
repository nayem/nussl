import warnings
from typing import Iterable

from torch.utils.data import Dataset

from .. import AudioSignal
from . import transforms as tfm
import tqdm


class BaseDataset(Dataset, Iterable):
    """
    The BaseDataset class is the starting point for all dataset hooks
    in nussl. To subclass BaseDataset, you only have to implement two 
    functions:

    - ``get_items``: a function that is passed the folder and generates a
      list of items that will be processed by the next function. The
      number of items in the list will dictate len(dataset). Must return
      a list.
    - ``process_item``: this function processes a single item in the list
      generated by get_items. Must return a dictionary.

    After process_item is called, a set of Transforms can be applied to the 
    output of process_item. If no transforms are defined (``self.transforms = None``),
    then the output of process_item is returned by self[i]. For implemented
    Transforms, see nussl.datasets.transforms. For example, 
    PhaseSpectrumApproximation will add three new keys to the output dictionary
    of process_item:

    - mix_magnitude: the magnitude spectrogram of the mixture
    - source_magnitudes: the magnitude spectrogram of each source
    - ideal_binary_mask: the ideal binary mask for each source

    The transforms are applied in sequence using transforms.Compose. 
    Not all sequences of transforms will be valid (e.g. if you pop a key in
    one transform but a later transform operates on that key, you will get
    an error).

    For examples of subclassing, see ``nussl.datasets.hooks``.
    
    Args:
        folder (str): location that should be processed to produce the list of files

        transform (transforms.* object, optional): A transforms to apply to the output of
          ``self.process_item``. If using transforms.Compose, each transform will be
          applied in sequence. Defaults to None.

        sample_rate (int, optional): Sample rate to use for each audio files. If
          audio file sample rate doesn't match, it will be resampled on the fly.
          If None, uses the default sample rate. Defaults to None.

        stft_params (STFTParams, optional): STFTParams object defining window_length,
          hop_length, and window_type that will be set for each AudioSignal object. 
          Defaults to None (32ms window length, 8ms hop, 'hann' window).

        num_channels (int, optional): Number of channels to make each AudioSignal
          object conform to. If an audio signal in your dataset has fewer channels
          than ``num_channels``, a warning is raised, as the behavior in this case
          is undefined. Defaults to None.

        strict_sample_rate (bool, optional): Whether to raise an error if 
    
    Raises:
        DataSetException: Exceptions are raised if the output of the implemented
            functions by the subclass don't match the specification.
    """
    def __init__(self, folder, transform=None, sample_rate=None, stft_params=None,
                 num_channels=None, strict_sample_rate=True, cache_populated=False):
        self.folder = folder
        self.items = self.get_items(self.folder)
        self.transform = transform

        self.cache_populated = cache_populated
        
        self.stft_params = stft_params
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.strict_sample_rate = strict_sample_rate

        if not isinstance(self.items, list):
            raise DataSetException("Output of self.get_items must be a list!")
        
        # getting one item in order to set up parameters for audio
        # signals if necessary, if there are any items
        if self.items:
            self.process_item(self.items[0])

    def filter_items_by_condition(self, func):
        """
        Filter the items in the list according to a function that takes 
        in both the dataset as well as the item currently be processed.
        If the item in the list passes the condition, then it is kept
        in the list. Otherwise it is taken out of the list. For example,
        a function that would get rid of an item if it is below some 
        minimum number of seconds would look like this:

        .. code-block:: python

            min_length = 1 # in seconds

            # self here refers to the dataset
            def remove_short_audio(self, item):
                processed_item = self.process_item(item)
                mix_length = processed_item['mix'].signal_duration
                if mix_length < min_length:
                    return False
                return True
            
            dataset.items # contains all items
            dataset.filter_items_by_condition(remove_short_audio)
            dataset.items # contains only items longer than min length
            
        Args:
            func (function): A function that takes in two arguments: the dataset and
              this dataset object (self). The function must return a bool.
        """
        filtered_items = []
        n_removed = 0
        desc = f"Filtered {n_removed} items out of dataset"
        pbar = tqdm.tqdm(self.items, desc=desc)
        for item in pbar:
            check = func(self, item)
            if not isinstance(check, bool):
                raise DataSetException(
                    "Output of filter function must be True or False!"
                )
            if check:
                filtered_items.append(item)
            else:
                n_removed += 1
            pbar.set_description(f"Filtered {n_removed} items out of dataset")
        self.items = filtered_items


    @property
    def cache_populated(self):
        return self._cache_populated

    @cache_populated.setter
    def cache_populated(self, value):
        self.post_cache_transforms = []
        cache_transform = None

        transforms = (
            self.transform.transforms 
            if isinstance(self.transform, tfm.Compose) 
            else [self.transform])

        found_cache_transform = False
        for t in transforms:
            if isinstance(t, tfm.Cache):
                found_cache_transform = True
                cache_transform = t
            if found_cache_transform:
                self.post_cache_transforms.append(t)

        if not found_cache_transform:
            # there is no cache transform
            self._cache_populated = False
        else:
            self._cache_populated = value
            cache_transform.cache_size = len(self)
            cache_transform.overwrite = not value

            self.post_cache_transforms = tfm.Compose(
                self.post_cache_transforms)

    def get_items(self, folder):
        """
        This function must be implemented by whatever class inherits BaseDataset.
        It should return a list of items in the given folder, each of which is 
        processed by process_items in some way to produce mixes, sources, class
        labels, etc.

        Args:
            folder (str): location that should be processed to produce the list of files.

        Returns:
            list: list of items that should be processed
        """
        raise NotImplementedError()

    def __len__(self):
        """
        Gets the length of the dataset (the number of items that will be processed).

        Returns:
            int: Length of the dataset (``len(self.items)``).
        """
        return len(self.items)

    def __getitem__(self, i):
        """
        Processes a single item in ``self.items`` using ``self.process_item``.
        The output of ``self.process_item`` is further passed through bunch of
        of transforms if they are defined in parallel. If you want to have
        a set of transforms that depend on each other, then you should compose them
        into a single transforms and then pass it into here. The output of each
        transform is added to an output dictionary which is returned by this
        function.
        
        Args:
            i (int): Index of the dataset to return. Indexes ``self.items``.

        Returns:
            dict: Dictionary with keys and values corresponding to the processed
                item after being put through the set of transforms (if any are
                defined).
        """
        
        if self.cache_populated:
            data = {'index': i}
            data = self.post_cache_transforms(data)
        else:
            data = self.process_item(self.items[i])

            if not isinstance(data, dict):
                raise DataSetException(
                    "The output of process_item must be a dictionary!")

            if self.transform:
                data['index'] = i
                data = self.transform(data)

                if not isinstance(data, dict):
                    raise tfm.TransformException(
                        "The output of transform must be a dictionary!")

        return data

    def __iter__(self):
        """
        Calls ``self.__getitem__`` from ``0`` to ``self.__len__()``.
        Required when inheriting Iterable.

        Yields:
            dict: Dictionary with keys and values corresponding to the processed
                item after being put through the set of transforms (if any are
                defined).
        """
        for i in range(len(self)):
            yield self[i]

    def process_item(self, item):
        """Each file returned by get_items is processed by this function. For example,
        if each file is a json file containing the paths to the mixture and sources, 
        then this function should parse the json file and load the mixture and sources
        and return them.

        Exact behavior of this functionality is determined by implementation by subclass.

        Args:
            item (object): the item that will be processed by this function. Input depends
              on implementation of ``self.get_items``.

        Returns:
            This should return a dictionary that gets processed by the transforms.
        """
        raise NotImplementedError()

    def _load_audio_file(self, path_to_audio_file, **kwargs):
        """
        Loads audio file at given path. Uses AudioSignal to load the audio data
        from disk.

        Args:
            path_to_audio_file: relative or absolute path to file to load
            kwargs: Keyword arguments to AudioSignal.

        Returns:
            AudioSignal: loaded AudioSignal object of path_to_audio_file
        """
        audio_signal = AudioSignal(path_to_audio_file, **kwargs)
        self._setup_audio_signal(audio_signal)
        return audio_signal
    
    def _load_audio_from_array(self, audio_data, sample_rate=None):
        """
        Loads the audio data into an AudioSignal object with the appropriate 
        sample rate.
        
        Args:
            audio_data (np.ndarray): numpy array containing the samples containing
              the audio data.

            sample_rate (int): the sample rate at which to load the audio file. 
              If None, self.sample_rate or the sample rate of the actual file is used. 
              Defaults to None.
        
        Returns:
            AudioSignal: loaded AudioSignal object of audio_data
        """
        sample_rate = sample_rate if sample_rate else self.sample_rate
        audio_signal = AudioSignal(
            audio_data_array=audio_data, sample_rate=sample_rate)
        self._setup_audio_signal(audio_signal)
        return audio_signal

    def _setup_audio_signal(self, audio_signal):
        """
        You will want every item from a dataset to be uniform in sample rate, STFT
        parameters, and number of channels. This function takes an audio signal 
        object loaded by the dataset and uses it to set the sample rate, STFT parameters,
        and the number of channels. If ``self.sample_rate``, ``self.stft_params``, and
        ``self.num_channels`` are set at construction time of the dataset, then the
        opposite happens - attributes of the AudioSignal object are set to the desired
        values.
        
        Args:
            audio_signal (AudioSignal): AudioSignal object to query to set the parameters
              of this dataset or to set the parameters of, according to what is in the 
              dataset.
        """
        if self.sample_rate and self.sample_rate != audio_signal.sample_rate:
            if self.strict_sample_rate:
                raise DataSetException(
                    f"All audio files should have been the same sample rate already " 
                    f"because self.strict_sample_rate = True. Please resample or "
                    f"turn set self.strict_sample_rate = False"
                )
            audio_signal.resample(self.sample_rate)  
        else:
            self.sample_rate = audio_signal.sample_rate

        # set audio signal attributes to requested values, if they exist
        if self.stft_params:
            audio_signal.stft_params = self.stft_params
        else:
            self.stft_params = audio_signal.stft_params

        if self.num_channels:
            if audio_signal.num_channels > self.num_channels:
                # pick the first ``self.num_channels`` channels 
                audio_signal.audio_data = audio_signal.audio_data[:self.num_channels]
            elif audio_signal.num_channels < self.num_channels:
                warnings.warn(
                    f"AudioSignal had {audio_signal.num_channels} channels "
                    f"but self.num_channels = {self.num_channels}. Unsure "
                    f"of what to do, so warning. You might want to make sure "
                    f"your dataset is uniform!"
                )
        else:
            self.num_channels = audio_signal.num_channels

class DataSetException(Exception):
    """
    Exception class for errors when working with data sets in nussl.
    """
    pass
