ElevenLabsLib - Unofficial API wrapper
=======================================================

.. note::
    For additional logging with this library, import logging and set the logging level to DEBUG.

.. _migrate-to-0.10:

Migrating from 0.9 to 0.10+
----------------------------

In the 0.10 release, many functions that deal with audio generation/playback have been deprecated, and new _v2 versions have been introduced.

Instead of specifying each option as a separate argument, they are now grouped together into two dataclasses, ``PlaybackOptions`` and ``GenerationOptions``.

For now the old versions are merely deprecated but they will be removed in the future.
Additionally, it is not possible to leverage the new settings of the V2 english model with the deprecated functions.

Here's an example of how to migrate, using generate_and_stream_audio as an example.

The old function signature looked like this:

.. code-block:: python

   generate_stream_audio(prompt, portaudioDeviceID=None, stability=None,
                         similarity_boost=None, streamInBackground=False,
                         onPlaybackStart=lambda: None, onPlaybackEnd=lambda: None,
                         model_id="eleven_monolingual_v1", latencyOptimizationLevel=0)

Now, the new function signature looks like this:

.. code-block:: python

   generate_stream_audio_v2(prompt, playbackOptions, generationOptions)

.. note::

   Similar changes apply to many other functions.

To migrate your existing code, follow these steps:

1. Import the necessary dataclasses:

   .. code-block:: python

      from elevenlabslib import PlaybackOptions, GenerationOptions

2. Create instances of ``PlaybackOptions`` and ``GenerationOptions`` with the
   appropriate settings:

   .. code-block:: python

      playbackOptions = PlaybackOptions(runInBackground=True, portaudioDeviceID=1)
      generationOptions = GenerationOptions(model_id="new_model_id")

3. Call the new functions with your text prompt and the options instances:

   .. code-block:: python

      result = voice.generate_stream_audio_v2("Hello, world!",
                                                   playbackOptions,
                                                   generationOptions)

Please refer to the :class:`PlaybackOptions <elevenlabslib.helpers.PlaybackOptions>` and
:class:`GenerationOptions <elevenlabslib.helpers.GenerationOptions>` sections for more information about
the available settings in these dataclasses.

.. toctree::
    source/api/class-index.rst
    source/api/helpers.rst
    source/examples.md
    :maxdepth: 3
