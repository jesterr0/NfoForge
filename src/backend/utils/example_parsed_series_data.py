from datetime import datetime

from pymediainfo import MediaInfo

from src.enums.media_type import MediaType
from src.payloads.media_search import MediaSearchPayload

current_year = datetime.now().year

EXAMPLE_FOLDER_NAME = "Series.Name.S03.BluRay.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup"
EXAMPLE_FILE_NAME_1 = (
    "Series.Name.S03E01.Episode.Name.1.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup.mkv"
)
EXAMPLE_FILE_NAME_2 = (
    "Series.Name.S03E01.Episode.Name.2.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup.mkv"
)
EXAMPLE_FILE_NAME_3 = (
    "Series.Name.S03E01.Episode.Name.3.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup.mkv"
)
EXAMPLE_FILE_NAME_4 = (
    "Series.Name.S03E01.Episode.Name.4.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup.mkv"
)
EXAMPLE_FILE_NAME_5 = (
    "Series.Name.S03E01.Episode.Name.5.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup.mkv"
)
EXAMPLE_FILE_NAME_6 = (
    "Series.Name.S03E01.Episode.Name.6.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup.mkv"
)
EXAMPLE_FILE_NAME_7 = (
    "Series.Name.S03E01.Episode.Name.7.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup.mkv"
)
EXAMPLE_FILE_NAME_8 = (
    "Series.Name.S03E01.Episode.Name.8.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup.mkv"
)
EXAMPLE_FILE_NAME_9 = (
    "Series.Name.S03E01.Episode.Name.9.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup.mkv"
)
EXAMPLE_FILE_NAME_10 = (
    "Series.Name.S03E01.Episode.Name.10.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup.mkv"
)

# fmt: off
_EXAMPLE_MEDIAINFO_XML_DATA = """\
<?xml version="1.0" encoding="UTF-8"?>
<Mediainfo version="25.04">
<File>
<track type="General">
<Count>359</Count>
<Count_of_stream_of_this_kind>1</Count_of_stream_of_this_kind>
<Kind_of_stream>General</Kind_of_stream>
<Kind_of_stream>General</Kind_of_stream>
<Stream_identifier>0</Stream_identifier>
<Unique_ID>48697611812023127731823097199478714321</Unique_ID>
<Unique_ID>48697611812023127731823097199478714321 (0x24A2D1A22D9AD8C711C0D48D41782FD1)</Unique_ID>
<Count_of_video_streams>1</Count_of_video_streams>
<Count_of_audio_streams>4</Count_of_audio_streams>
<Count_of_text_streams>1</Count_of_text_streams>
<Count_of_menu_streams>1</Count_of_menu_streams>
<Video_Format_List>AVC</Video_Format_List>
<Video_Format_WithHint_List>AVC</Video_Format_WithHint_List>
<Codecs_Video>AVC</Codecs_Video>
<Audio_Format_List>MLP FBA / AC-3 / AC-3 / AC-3</Audio_Format_List>
<Audio_Format_WithHint_List>MLP FBA / AC-3 / AC-3 / AC-3</Audio_Format_WithHint_List>
<Audio_codecs>MLP FBA / AC-3 / AC-3 / AC-3</Audio_codecs>
<Audio_Language_List>English / English / English / English</Audio_Language_List>
<Audio_Channels_Total>16</Audio_Channels_Total>
<Text_Format_List>PGS</Text_Format_List>
<Text_Format_WithHint_List>PGS</Text_Format_WithHint_List>
<Text_codecs>PGS</Text_codecs>
<Text_Language_List>English</Text_Language_List>
<Complete_name>Series.Name.S03E01.Episode.Name.1.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup.mkv</Complete_name>
<Folder_name>Series.Name.S03.BluRay.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup</Folder_name>
<File_name_extension>Series.Name.S03E01.Episode.Name.1.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup.mkv</File_name_extension>
<File_name>Series.Name.S03E01.Episode.Name.1.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup</File_name>
<File_extension>mkv</File_extension>
<Format>Matroska</Format>
<Format>Matroska</Format>
<Format_Url>https://matroska.org/downloads/windows.html</Format_Url>
<Format_Extensions_usually_used>mkv mk3d mka mks</Format_Extensions_usually_used>
<Commercial_name>Matroska</Commercial_name>
<Format_version>Version 4</Format_version>
<File_size>2179567234</File_size>
<File_size>2.03 GiB</File_size>
<File_size>2 GiB</File_size>
<File_size>2.0 GiB</File_size>
<File_size>2.03 GiB</File_size>
<File_size>2.030 GiB</File_size>
<Duration>1402496</Duration>
<Duration>23 min 22 s</Duration>
<Duration>23 min 22 s 496 ms</Duration>
<Duration>23 min 22 s</Duration>
<Duration>00:23:22.496</Duration>
<Duration>00:23:21:02</Duration>
<Duration>00:23:22.496 (00:23:21:02)</Duration>
<Overall_bit_rate_mode>VBR</Overall_bit_rate_mode>
<Overall_bit_rate_mode>Variable</Overall_bit_rate_mode>
<Overall_bit_rate>12432505</Overall_bit_rate>
<Overall_bit_rate>12.4 Mb/s</Overall_bit_rate>
<Frame_rate>23.976</Frame_rate>
<Frame_rate>23.976 FPS</Frame_rate>
<Frame_count>33626</Frame_count>
<Stream_size>12290742</Stream_size>
<Stream_size>11.7 MiB (1%)</Stream_size>
<Stream_size>12 MiB</Stream_size>
<Stream_size>12 MiB</Stream_size>
<Stream_size>11.7 MiB</Stream_size>
<Stream_size>11.72 MiB</Stream_size>
<Stream_size>11.7 MiB (1%)</Stream_size>
<Proportion_of_this_stream>0.00564</Proportion_of_this_stream>
<IsStreamable>Yes</IsStreamable>
<Title>Series Name S03E01 Episode Name 1</Title>
<Movie_name>Series Name S03E01 Episode Name 1</Movie_name>
<Encoded_date>2019-11-19 14:27:51 UTC</Encoded_date>
<File_creation_date>2025-08-21 13:25:00.970 UTC</File_creation_date>
<File_creation_date__local_>2025-08-21 09:25:00.970</File_creation_date__local_>
<File_last_modification_date>2025-08-21 13:26:52.799 UTC</File_last_modification_date>
<File_last_modification_date__local_>2025-08-21 09:26:52.799</File_last_modification_date__local_>
<Writing_application>mkvmerge v40.0.0 (&apos;Old Town Road + Pony&apos;) 64-bit</Writing_application>
<Writing_application>mkvmerge v40.0.0 (&apos;Old Town Road + Pony&apos;) 64-bit</Writing_application>
<Writing_library>libebml v1.3.9 + libmatroska v1.5.2</Writing_library>
<Writing_library>libebml v1.3.9 + libmatroska v1.5.2</Writing_library>
</track>
<track type="Video">
<Count>390</Count>
<Count_of_stream_of_this_kind>1</Count_of_stream_of_this_kind>
<Kind_of_stream>Video</Kind_of_stream>
<Kind_of_stream>Video</Kind_of_stream>
<Stream_identifier>0</Stream_identifier>
<StreamOrder>0</StreamOrder>
<ID>1</ID>
<ID>1</ID>
<Unique_ID>3116556513070564829</Unique_ID>
<Format>AVC</Format>
<Format>AVC</Format>
<Format_Info>Advanced Video Codec</Format_Info>
<Format_Url>http://developers.videolan.org/x264.html</Format_Url>
<Commercial_name>AVC</Commercial_name>
<Format_profile>High@L4.1</Format_profile>
<Format_settings>CABAC / 2 Ref Frames</Format_settings>
<Format_settings__CABAC>Yes</Format_settings__CABAC>
<Format_settings__CABAC>Yes</Format_settings__CABAC>
<Format_settings__Reference_frames>2</Format_settings__Reference_frames>
<Format_settings__Reference_frames>2 frames</Format_settings__Reference_frames>
<Format_settings__GOP>M=1, N=5</Format_settings__GOP>
<Format_settings__Slice_count>4</Format_settings__Slice_count>
<Format_settings__Slice_count>4 slices per frame</Format_settings__Slice_count>
<Internet_media_type>video/H264</Internet_media_type>
<Codec_ID>V_MPEG4/ISO/AVC</Codec_ID>
<Codec_ID_Url>http://ffdshow-tryout.sourceforge.net/</Codec_ID_Url>
<Duration>1402485.000000</Duration>
<Duration>23 min 22 s</Duration>
<Duration>23 min 22 s 485 ms</Duration>
<Duration>23 min 22 s</Duration>
<Duration>00:23:22.485</Duration>
<Duration>00:23:21:02</Duration>
<Duration>00:23:22.485 (00:23:21:02)</Duration>
<Bit_rate_mode>VBR</Bit_rate_mode>
<Bit_rate_mode>Variable</Bit_rate_mode>
<Bit_rate>8372395</Bit_rate>
<Bit_rate>8 372 kb/s</Bit_rate>
<Maximum_bit_rate>36241408</Maximum_bit_rate>
<Maximum_bit_rate>36.2 Mb/s</Maximum_bit_rate>
<Width>1920</Width>
<Width>1 920 pixels</Width>
<Height>1080</Height>
<Height>1 080 pixels</Height>
<Stored_Height>1088</Stored_Height>
<Sampled_Width>1920</Sampled_Width>
<Sampled_Height>1080</Sampled_Height>
<Pixel_aspect_ratio>1.000</Pixel_aspect_ratio>
<Display_aspect_ratio>1.778</Display_aspect_ratio>
<Display_aspect_ratio>16:9</Display_aspect_ratio>
<Frame_rate_mode>CFR</Frame_rate_mode>
<Frame_rate_mode>Constant</Frame_rate_mode>
<Frame_rate>23.976</Frame_rate>
<Frame_rate>23.976 (24000/1001) FPS</Frame_rate>
<FrameRate_Num>24000</FrameRate_Num>
<FrameRate_Den>1001</FrameRate_Den>
<Frame_count>33626</Frame_count>
<Color_space>YUV</Color_space>
<Chroma_subsampling>4:2:0</Chroma_subsampling>
<Chroma_subsampling>4:2:0</Chroma_subsampling>
<Bit_depth>8</Bit_depth>
<Bit_depth>8 bits</Bit_depth>
<Scan_type>Progressive</Scan_type>
<Scan_type>Progressive</Scan_type>
<Bits__Pixel_Frame_>0.168</Bits__Pixel_Frame_>
<Delay>0</Delay>
<Delay>00:00:00.000</Delay>
<Delay>00:00:00:00</Delay>
<Delay>00:00:00.000 (00:00:00:00)</Delay>
<Delay__origin>Container</Delay__origin>
<Delay__origin>Container</Delay__origin>
<Stream_size>1467769958</Stream_size>
<Stream_size>1.37 GiB (67%)</Stream_size>
<Stream_size>1 GiB</Stream_size>
<Stream_size>1.4 GiB</Stream_size>
<Stream_size>1.37 GiB</Stream_size>
<Stream_size>1.367 GiB</Stream_size>
<Stream_size>1.37 GiB (67%)</Stream_size>
<Proportion_of_this_stream>0.67342</Proportion_of_this_stream>
<Default>Yes</Default>
<Default>Yes</Default>
<Forced>No</Forced>
<Forced>No</Forced>
<Buffer_size>29687808</Buffer_size>
</track>
<track type="Audio" typeorder="1">
<Count>285</Count>
<Count_of_stream_of_this_kind>4</Count_of_stream_of_this_kind>
<Kind_of_stream>Audio</Kind_of_stream>
<Kind_of_stream>Audio</Kind_of_stream>
<Stream_identifier>0</Stream_identifier>
<Stream_identifier>1</Stream_identifier>
<StreamOrder>1</StreamOrder>
<ID>2</ID>
<ID>2</ID>
<Unique_ID>11254018164315169758</Unique_ID>
<Format>MLP FBA</Format>
<Format>MLP FBA</Format>
<Format_Info>Meridian Lossless Packing FBA</Format_Info>
<Commercial_name>Dolby TrueHD</Commercial_name>
<Commercial_name>Dolby TrueHD</Commercial_name>
<Codec_ID>A_TRUEHD</Codec_ID>
<Codec_ID_Url>http://www.dolby.com/consumer/technology/trueHD.html</Codec_ID_Url>
<Duration>1402485.000000</Duration>
<Duration>23 min 22 s</Duration>
<Duration>23 min 22 s 485 ms</Duration>
<Duration>23 min 22 s</Duration>
<Duration>00:23:22.485</Duration>
<Duration>00:23:22.485</Duration>
<Bit_rate_mode>VBR</Bit_rate_mode>
<Bit_rate_mode>Variable</Bit_rate_mode>
<Bit_rate>2991774</Bit_rate>
<Bit_rate>2 992 kb/s</Bit_rate>
<Maximum_bit_rate>4359000</Maximum_bit_rate>
<Maximum_bit_rate>4 359 kb/s</Maximum_bit_rate>
<Channel_s_>6</Channel_s_>
<Channel_s_>6 channels</Channel_s_>
<Channel_positions>Front: L C R, Side: L R, LFE</Channel_positions>
<Channel_positions>3/2/0.1</Channel_positions>
<Channel_layout>L R C LFE Ls Rs</Channel_layout>
<Samples_per_frame>40</Samples_per_frame>
<Sampling_rate>48000</Sampling_rate>
<Sampling_rate>48.0 kHz</Sampling_rate>
<Samples_count>67319280</Samples_count>
<Frame_rate>1200.000</Frame_rate>
<Frame_rate>1 200.000 FPS (40 SPF)</Frame_rate>
<FrameRate_Num>1200</FrameRate_Num>
<FrameRate_Den>1</FrameRate_Den>
<Frame_count>1682982</Frame_count>
<Compression_mode>Lossless</Compression_mode>
<Compression_mode>Lossless</Compression_mode>
<Delay>0</Delay>
<Delay>00:00:00.000</Delay>
<Delay>00:00:00.000</Delay>
<Delay__origin>Container</Delay__origin>
<Delay__origin>Container</Delay__origin>
<Delay_relative_to_video>0</Delay_relative_to_video>
<Delay_relative_to_video>00:00:00.000</Delay_relative_to_video>
<Delay_relative_to_video>00:00:00.000</Delay_relative_to_video>
<Stream_size>524489944</Stream_size>
<Stream_size>500 MiB (24%)</Stream_size>
<Stream_size>500 MiB</Stream_size>
<Stream_size>500 MiB</Stream_size>
<Stream_size>500 MiB</Stream_size>
<Stream_size>500.2 MiB</Stream_size>
<Stream_size>500 MiB (24%)</Stream_size>
<Proportion_of_this_stream>0.24064</Proportion_of_this_stream>
<Title>TrueHD 5.1</Title>
<Language>en</Language>
<Language>English</Language>
<Language>English</Language>
<Language>en</Language>
<Language>eng</Language>
<Language>en</Language>
<Default>Yes</Default>
<Default>Yes</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Audio" typeorder="2">
<Count>326</Count>
<Count_of_stream_of_this_kind>4</Count_of_stream_of_this_kind>
<Kind_of_stream>Audio</Kind_of_stream>
<Kind_of_stream>Audio</Kind_of_stream>
<Stream_identifier>1</Stream_identifier>
<Stream_identifier>2</Stream_identifier>
<StreamOrder>2</StreamOrder>
<ID>3</ID>
<ID>3</ID>
<Unique_ID>10361330195630253603</Unique_ID>
<Format>AC-3</Format>
<Format>AC-3</Format>
<Format_Info>Audio Coding 3</Format_Info>
<Format_Url>https://en.wikipedia.org/wiki/AC3</Format_Url>
<Commercial_name>Dolby Digital</Commercial_name>
<Commercial_name>Dolby Digital</Commercial_name>
<Format_settings__Endianness>Big</Format_settings__Endianness>
<Codec_ID>A_AC3</Codec_ID>
<Duration>1402496.000000</Duration>
<Duration>23 min 22 s</Duration>
<Duration>23 min 22 s 496 ms</Duration>
<Duration>23 min 22 s</Duration>
<Duration>00:23:22.496</Duration>
<Duration>00:23:22.496</Duration>
<Bit_rate_mode>CBR</Bit_rate_mode>
<Bit_rate_mode>Constant</Bit_rate_mode>
<Bit_rate>448000</Bit_rate>
<Bit_rate>448 kb/s</Bit_rate>
<Channel_s_>6</Channel_s_>
<Channel_s_>6 channels</Channel_s_>
<Channel_positions>Front: L C R, Side: L R, LFE</Channel_positions>
<Channel_positions>3/2/0.1</Channel_positions>
<Channel_layout>L R C LFE Ls Rs</Channel_layout>
<Samples_per_frame>1536</Samples_per_frame>
<Sampling_rate>48000</Sampling_rate>
<Sampling_rate>48.0 kHz</Sampling_rate>
<Samples_count>67319808</Samples_count>
<Frame_rate>31.250</Frame_rate>
<Frame_rate>31.250 FPS (1536 SPF)</Frame_rate>
<Frame_count>43828</Frame_count>
<Compression_mode>Lossy</Compression_mode>
<Compression_mode>Lossy</Compression_mode>
<Delay>0</Delay>
<Delay>00:00:00.000</Delay>
<Delay>00:00:00.000</Delay>
<Delay__origin>Container</Delay__origin>
<Delay__origin>Container</Delay__origin>
<Delay_relative_to_video>0</Delay_relative_to_video>
<Delay_relative_to_video>00:00:00.000</Delay_relative_to_video>
<Delay_relative_to_video>00:00:00.000</Delay_relative_to_video>
<Stream_size>78539776</Stream_size>
<Stream_size>74.9 MiB (4%)</Stream_size>
<Stream_size>75 MiB</Stream_size>
<Stream_size>75 MiB</Stream_size>
<Stream_size>74.9 MiB</Stream_size>
<Stream_size>74.90 MiB</Stream_size>
<Stream_size>74.9 MiB (4%)</Stream_size>
<Proportion_of_this_stream>0.03603</Proportion_of_this_stream>
<Title>AC-3 5.1</Title>
<Language>en</Language>
<Language>English</Language>
<Language>English</Language>
<Language>en</Language>
<Language>eng</Language>
<Language>en</Language>
<Service_kind>CM</Service_kind>
<Service_kind>Complete Main</Service_kind>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
<bsid>6</bsid>
<Dialog_Normalization>-31</Dialog_Normalization>
<Dialog_Normalization>-31 dB</Dialog_Normalization>
<compr>-0.28</compr>
<compr>-0.28 dB</compr>
<acmod>7</acmod>
<lfeon>1</lfeon>
<cmixlev>-3.0</cmixlev>
<cmixlev>-3.0 dB</cmixlev>
<surmixlev>-3 dB</surmixlev>
<surmixlev>-3 dB</surmixlev>
<dmixmod>Lt/Rt</dmixmod>
<ltrtcmixlev>-3.0</ltrtcmixlev>
<ltrtcmixlev>-3.0 dB</ltrtcmixlev>
<ltrtsurmixlev>-3.0</ltrtsurmixlev>
<ltrtsurmixlev>-3.0 dB</ltrtsurmixlev>
<lorocmixlev>-3.0</lorocmixlev>
<lorocmixlev>-3.0 dB</lorocmixlev>
<lorosurmixlev>-3.0</lorosurmixlev>
<lorosurmixlev>-3.0 dB</lorosurmixlev>
<dialnorm_Average>-31</dialnorm_Average>
<dialnorm_Average>-31 dB</dialnorm_Average>
<dialnorm_Minimum>-31</dialnorm_Minimum>
<dialnorm_Minimum>-31 dB</dialnorm_Minimum>
<dialnorm_Maximum>-31</dialnorm_Maximum>
<dialnorm_Maximum>-31 dB</dialnorm_Maximum>
<dialnorm_Count>78</dialnorm_Count>
<compr_Average>0.64</compr_Average>
<compr_Average>0.64 dB</compr_Average>
<compr_Minimum>-4.53</compr_Minimum>
<compr_Minimum>-4.53 dB</compr_Minimum>
<compr_Maximum>2.77</compr_Maximum>
<compr_Maximum>2.77 dB</compr_Maximum>
<compr_Count>76</compr_Count>
<dynrng_Average>0.62</dynrng_Average>
<dynrng_Average>0.62 dB</dynrng_Average>
<dynrng_Minimum>-1.48</dynrng_Minimum>
<dynrng_Minimum>-1.48 dB</dynrng_Minimum>
<dynrng_Maximum>2.15</dynrng_Maximum>
<dynrng_Maximum>2.15 dB</dynrng_Maximum>
<dynrng_Count>78</dynrng_Count>
</track>
<track type="Audio" typeorder="3">
<Count>323</Count>
<Count_of_stream_of_this_kind>4</Count_of_stream_of_this_kind>
<Kind_of_stream>Audio</Kind_of_stream>
<Kind_of_stream>Audio</Kind_of_stream>
<Stream_identifier>2</Stream_identifier>
<Stream_identifier>3</Stream_identifier>
<StreamOrder>3</StreamOrder>
<ID>4</ID>
<ID>4</ID>
<Unique_ID>10319699278594842107</Unique_ID>
<Format>AC-3</Format>
<Format>AC-3</Format>
<Format_Info>Audio Coding 3</Format_Info>
<Format_Url>https://en.wikipedia.org/wiki/AC3</Format_Url>
<Commercial_name>Dolby Digital</Commercial_name>
<Commercial_name>Dolby Digital</Commercial_name>
<Format_settings__Endianness>Big</Format_settings__Endianness>
<Codec_ID>A_AC3</Codec_ID>
<Duration>1402496.000000</Duration>
<Duration>23 min 22 s</Duration>
<Duration>23 min 22 s 496 ms</Duration>
<Duration>23 min 22 s</Duration>
<Duration>00:23:22.496</Duration>
<Duration>00:23:22.496</Duration>
<Bit_rate_mode>CBR</Bit_rate_mode>
<Bit_rate_mode>Constant</Bit_rate_mode>
<Bit_rate>224000</Bit_rate>
<Bit_rate>224 kb/s</Bit_rate>
<Channel_s_>2</Channel_s_>
<Channel_s_>2 channels</Channel_s_>
<Channel_positions>Front: L R</Channel_positions>
<Channel_positions>2/0/0</Channel_positions>
<Channel_layout>L R</Channel_layout>
<Samples_per_frame>1536</Samples_per_frame>
<Sampling_rate>48000</Sampling_rate>
<Sampling_rate>48.0 kHz</Sampling_rate>
<Samples_count>67319808</Samples_count>
<Frame_rate>31.250</Frame_rate>
<Frame_rate>31.250 FPS (1536 SPF)</Frame_rate>
<Frame_count>43828</Frame_count>
<Compression_mode>Lossy</Compression_mode>
<Compression_mode>Lossy</Compression_mode>
<Delay>0</Delay>
<Delay>00:00:00.000</Delay>
<Delay>00:00:00.000</Delay>
<Delay__origin>Container</Delay__origin>
<Delay__origin>Container</Delay__origin>
<Delay_relative_to_video>0</Delay_relative_to_video>
<Delay_relative_to_video>00:00:00.000</Delay_relative_to_video>
<Delay_relative_to_video>00:00:00.000</Delay_relative_to_video>
<Stream_size>39269888</Stream_size>
<Stream_size>37.5 MiB (2%)</Stream_size>
<Stream_size>37 MiB</Stream_size>
<Stream_size>37 MiB</Stream_size>
<Stream_size>37.5 MiB</Stream_size>
<Stream_size>37.45 MiB</Stream_size>
<Stream_size>37.5 MiB (2%)</Stream_size>
<Proportion_of_this_stream>0.01802</Proportion_of_this_stream>
<Title>Commentary by Creators Dan Harmon, Justin Roiland, Writer Mike McMahan, Director Juan Meza-Léon and John Mayer</Title>
<Language>en</Language>
<Language>English</Language>
<Language>English</Language>
<Language>en</Language>
<Language>eng</Language>
<Language>en</Language>
<Service_kind>CM</Service_kind>
<Service_kind>Complete Main</Service_kind>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
<bsid>6</bsid>
<Dialog_Normalization>-31</Dialog_Normalization>
<Dialog_Normalization>-31 dB</Dialog_Normalization>
<compr>-0.28</compr>
<compr>-0.28 dB</compr>
<dsurmod>1</dsurmod>
<dsurmod>Not Dolby Surround encoded</dsurmod>
<acmod>2</acmod>
<lfeon>0</lfeon>
<ltrtcmixlev>-3.0</ltrtcmixlev>
<ltrtcmixlev>-3.0 dB</ltrtcmixlev>
<ltrtsurmixlev>-3.0</ltrtsurmixlev>
<ltrtsurmixlev>-3.0 dB</ltrtsurmixlev>
<lorocmixlev>-3.0</lorocmixlev>
<lorocmixlev>-3.0 dB</lorocmixlev>
<lorosurmixlev>-3.0</lorosurmixlev>
<lorosurmixlev>-3.0 dB</lorosurmixlev>
<dialnorm_Average>-31</dialnorm_Average>
<dialnorm_Average>-31 dB</dialnorm_Average>
<dialnorm_Minimum>-31</dialnorm_Minimum>
<dialnorm_Minimum>-31 dB</dialnorm_Minimum>
<dialnorm_Maximum>-31</dialnorm_Maximum>
<dialnorm_Maximum>-31 dB</dialnorm_Maximum>
<dialnorm_Count>78</dialnorm_Count>
<compr_Average>0.98</compr_Average>
<compr_Average>0.98 dB</compr_Average>
<compr_Minimum>-1.80</compr_Minimum>
<compr_Minimum>-1.80 dB</compr_Minimum>
<compr_Maximum>2.77</compr_Maximum>
<compr_Maximum>2.77 dB</compr_Maximum>
<compr_Count>76</compr_Count>
<dynrng_Average>0.67</dynrng_Average>
<dynrng_Average>0.67 dB</dynrng_Average>
<dynrng_Minimum>-1.16</dynrng_Minimum>
<dynrng_Minimum>-1.16 dB</dynrng_Minimum>
<dynrng_Maximum>2.15</dynrng_Maximum>
<dynrng_Maximum>2.15 dB</dynrng_Maximum>
<dynrng_Count>78</dynrng_Count>
</track>
<track type="Audio" typeorder="4">
<Count>323</Count>
<Count_of_stream_of_this_kind>4</Count_of_stream_of_this_kind>
<Kind_of_stream>Audio</Kind_of_stream>
<Kind_of_stream>Audio</Kind_of_stream>
<Stream_identifier>3</Stream_identifier>
<Stream_identifier>4</Stream_identifier>
<StreamOrder>4</StreamOrder>
<ID>5</ID>
<ID>5</ID>
<Unique_ID>16267354825802725600</Unique_ID>
<Format>AC-3</Format>
<Format>AC-3</Format>
<Format_Info>Audio Coding 3</Format_Info>
<Format_Url>https://en.wikipedia.org/wiki/AC3</Format_Url>
<Commercial_name>Dolby Digital</Commercial_name>
<Commercial_name>Dolby Digital</Commercial_name>
<Format_settings__Endianness>Big</Format_settings__Endianness>
<Codec_ID>A_AC3</Codec_ID>
<Duration>1402496.000000</Duration>
<Duration>23 min 22 s</Duration>
<Duration>23 min 22 s 496 ms</Duration>
<Duration>23 min 22 s</Duration>
<Duration>00:23:22.496</Duration>
<Duration>00:23:22.496</Duration>
<Bit_rate_mode>CBR</Bit_rate_mode>
<Bit_rate_mode>Constant</Bit_rate_mode>
<Bit_rate>224000</Bit_rate>
<Bit_rate>224 kb/s</Bit_rate>
<Channel_s_>2</Channel_s_>
<Channel_s_>2 channels</Channel_s_>
<Channel_positions>Front: L R</Channel_positions>
<Channel_positions>2/0/0</Channel_positions>
<Channel_layout>L R</Channel_layout>
<Samples_per_frame>1536</Samples_per_frame>
<Sampling_rate>48000</Sampling_rate>
<Sampling_rate>48.0 kHz</Sampling_rate>
<Samples_count>67319808</Samples_count>
<Frame_rate>31.250</Frame_rate>
<Frame_rate>31.250 FPS (1536 SPF)</Frame_rate>
<Frame_count>43828</Frame_count>
<Compression_mode>Lossy</Compression_mode>
<Compression_mode>Lossy</Compression_mode>
<Delay>0</Delay>
<Delay>00:00:00.000</Delay>
<Delay>00:00:00.000</Delay>
<Delay__origin>Container</Delay__origin>
<Delay__origin>Container</Delay__origin>
<Delay_relative_to_video>0</Delay_relative_to_video>
<Delay_relative_to_video>00:00:00.000</Delay_relative_to_video>
<Delay_relative_to_video>00:00:00.000</Delay_relative_to_video>
<Stream_size>39269888</Stream_size>
<Stream_size>37.5 MiB (2%)</Stream_size>
<Stream_size>37 MiB</Stream_size>
<Stream_size>37 MiB</Stream_size>
<Stream_size>37.5 MiB</Stream_size>
<Stream_size>37.45 MiB</Stream_size>
<Stream_size>37.5 MiB (2%)</Stream_size>
<Proportion_of_this_stream>0.01802</Proportion_of_this_stream>
<Title>Commentary by Guests Courtney Love and Marilyn Manson</Title>
<Language>en</Language>
<Language>English</Language>
<Language>English</Language>
<Language>en</Language>
<Language>eng</Language>
<Language>en</Language>
<Service_kind>CM</Service_kind>
<Service_kind>Complete Main</Service_kind>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
<bsid>6</bsid>
<Dialog_Normalization>-31</Dialog_Normalization>
<Dialog_Normalization>-31 dB</Dialog_Normalization>
<compr>-0.28</compr>
<compr>-0.28 dB</compr>
<dsurmod>1</dsurmod>
<dsurmod>Not Dolby Surround encoded</dsurmod>
<acmod>2</acmod>
<lfeon>0</lfeon>
<ltrtcmixlev>-3.0</ltrtcmixlev>
<ltrtcmixlev>-3.0 dB</ltrtcmixlev>
<ltrtsurmixlev>-3.0</ltrtsurmixlev>
<ltrtsurmixlev>-3.0 dB</ltrtsurmixlev>
<lorocmixlev>-3.0</lorocmixlev>
<lorocmixlev>-3.0 dB</lorocmixlev>
<lorosurmixlev>-3.0</lorosurmixlev>
<lorosurmixlev>-3.0 dB</lorosurmixlev>
<dialnorm_Average>-31</dialnorm_Average>
<dialnorm_Average>-31 dB</dialnorm_Average>
<dialnorm_Minimum>-31</dialnorm_Minimum>
<dialnorm_Minimum>-31 dB</dialnorm_Minimum>
<dialnorm_Maximum>-31</dialnorm_Maximum>
<dialnorm_Maximum>-31 dB</dialnorm_Maximum>
<dialnorm_Count>78</dialnorm_Count>
<compr_Average>0.95</compr_Average>
<compr_Average>0.95 dB</compr_Average>
<compr_Minimum>-1.80</compr_Minimum>
<compr_Minimum>-1.80 dB</compr_Minimum>
<compr_Maximum>2.77</compr_Maximum>
<compr_Maximum>2.77 dB</compr_Maximum>
<compr_Count>76</compr_Count>
<dynrng_Average>0.62</dynrng_Average>
<dynrng_Average>0.62 dB</dynrng_Average>
<dynrng_Minimum>-1.48</dynrng_Minimum>
<dynrng_Minimum>-1.48 dB</dynrng_Minimum>
<dynrng_Maximum>2.15</dynrng_Maximum>
<dynrng_Maximum>2.15 dB</dynrng_Maximum>
<dynrng_Count>78</dynrng_Count>
</track>
<track type="Text">
<Count>305</Count>
<Count_of_stream_of_this_kind>1</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>0</Stream_identifier>
<StreamOrder>5</StreamOrder>
<ID>6</ID>
<ID>6</ID>
<Unique_ID>10651012613879145588</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>1392600.000000</Duration>
<Duration>23 min 12 s</Duration>
<Duration>23 min 12 s 600 ms</Duration>
<Duration>23 min 12 s</Duration>
<Duration>00:23:12.600</Duration>
<Duration>00:21:23</Duration>
<Duration>00:23:12.600 (00:21:23)</Duration>
<Bit_rate>103042</Bit_rate>
<Bit_rate>103 kb/s</Bit_rate>
<Frame_rate>0.921</Frame_rate>
<Frame_rate>0.921 FPS</Frame_rate>
<Frame_count>1282</Frame_count>
<Count_of_elements>1282</Count_of_elements>
<Stream_size>17937038</Stream_size>
<Stream_size>17.1 MiB (1%)</Stream_size>
<Stream_size>17 MiB</Stream_size>
<Stream_size>17 MiB</Stream_size>
<Stream_size>17.1 MiB</Stream_size>
<Stream_size>17.11 MiB</Stream_size>
<Stream_size>17.1 MiB (1%)</Stream_size>
<Proportion_of_this_stream>0.00823</Proportion_of_this_stream>
<Title>English (SDH)</Title>
<Language>en</Language>
<Language>English</Language>
<Language>English</Language>
<Language>en</Language>
<Language>eng</Language>
<Language>en</Language>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Menu">
<Count>106</Count>
<Count_of_stream_of_this_kind>1</Count_of_stream_of_this_kind>
<Kind_of_stream>Menu</Kind_of_stream>
<Kind_of_stream>Menu</Kind_of_stream>
<Stream_identifier>0</Stream_identifier>
<Chapters_Pos_Begin>101</Chapters_Pos_Begin>
<Chapters_Pos_End>106</Chapters_Pos_End>
<_00_00_00000>en:Chapter 01</_00_00_00000>
<_00_01_23000>en:Chapter 02</_00_01_23000>
<_00_01_54823>en:Chapter 03</_00_01_54823>
<_00_09_55887>en:Chapter 04</_00_09_55887>
<_00_22_13874>en:Chapter 05</_00_22_13874>
</track>
</File>
</Mediainfo>"""
# fmt: on

EXAMPLE_MEDIAINFO_OBJ = MediaInfo(_EXAMPLE_MEDIAINFO_XML_DATA)

# fmt: off
EXAMPLE_MEDIAINFO_OUTPUT_STR = """\
General
Count                                    : 349
Count of stream of this kind             : 1
Kind of stream                           : General
Kind of stream                           : General
Stream identifier                        : 0
Unique ID                                : 48697611812023127731823097199478714321
Unique ID                                : 48697611812023127731823097199478714321 (0x24A2D1A22D9AD8C711C0D48D41782FD1)
Count of video streams                   : 1
Count of audio streams                   : 4
Count of text streams                    : 1
Count of menu streams                    : 1
Video_Format_List                        : AVC
Video_Format_WithHint_List               : AVC
Codecs Video                             : AVC
Audio_Format_List                        : MLP FBA / AC-3 / AC-3 / AC-3
Audio_Format_WithHint_List               : MLP FBA / AC-3 / AC-3 / AC-3
Audio codecs                             : MLP FBA / AC-3 / AC-3 / AC-3
Audio_Language_List                      : English / English / English / English
Audio_Channels_Total                     : 16
Text_Format_List                         : PGS
Text_Format_WithHint_List                : PGS
Text codecs                              : PGS
Text_Language_List                       : English
Complete name                            : Series.Name.S03E01.Episode.Name.1.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup.mkv
Folder name                              : Series.Name.S03.BluRay.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup
File name extension                      : Series.Name.S03E01.Episode.Name.1.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup.mkv
File name                                : Series.Name.S03E01.Episode.Name.1.1080p.TrueHD.5.1.AVC.REMUX-SomeGroup
File extension                           : mkv
Format                                   : Matroska
Format                                   : Matroska
Format/Url                               : https://matroska.org/downloads/windows.html
Format/Extensions usually used           : mkv mk3d mka mks
Commercial name                          : Matroska
Format version                           : Version 4
File size                                : 2179567234
File size                                : 2.03 GiB
File size                                : 2 GiB
File size                                : 2.0 GiB
File size                                : 2.03 GiB
File size                                : 2.030 GiB
Duration                                 : 1402496
Duration                                 : 23 min 22 s
Duration                                 : 23 min 22 s 496 ms
Duration                                 : 23 min 22 s
Duration                                 : 00:23:22.496
Duration                                 : 00:23:21:02
Duration                                 : 00:23:22.496 (00:23:21:02)
Overall bit rate mode                    : VBR
Overall bit rate mode                    : Variable
Overall bit rate                         : 12432505
Overall bit rate                         : 12.4 Mb/s
Frame rate                               : 23.976
Frame rate                               : 23.976 FPS
Frame count                              : 33626
Stream size                              : 12290742
Stream size                              : 11.7 MiB (1%)
Stream size                              : 12 MiB
Stream size                              : 12 MiB
Stream size                              : 11.7 MiB
Stream size                              : 11.72 MiB
Stream size                              : 11.7 MiB (1%)
Proportion of this stream                : 0.00564
IsStreamable                             : Yes
Title                                    : Series Name (S03E01) Episode Name 1
Movie name                               : Series Name (S03E01) Episode Name 1
Encoded date                             : 2019-11-19 14:27:51 UTC
File creation date                       : 2025-08-21 13:25:00.970 UTC
File creation date (local)               : 2025-08-21 09:25:00.970
File last modification date              : 2025-08-21 13:26:52.799 UTC
File last modification date (local)      : 2025-08-21 09:26:52.799
Writing application                      : mkvmerge v40.0.0 ('Old Town Road + Pony') 64-bit
Writing application                      : mkvmerge v40.0.0 ('Old Town Road + Pony') 64-bit
Writing library                          : libebml v1.3.9 + libmatroska v1.5.2
Writing library                          : libebml v1.3.9 + libmatroska v1.5.2

Video
Count                                    : 390
Count of stream of this kind             : 1
Kind of stream                           : Video
Kind of stream                           : Video
Stream identifier                        : 0
StreamOrder                              : 0
ID                                       : 1
ID                                       : 1
Unique ID                                : 3116556513070564829
Format                                   : AVC
Format                                   : AVC
Format/Info                              : Advanced Video Codec
Format/Url                               : http://developers.videolan.org/x264.html
Commercial name                          : AVC
Format profile                           : High@L4.1
Format settings                          : CABAC / 2 Ref Frames
Format settings, CABAC                   : Yes
Format settings, CABAC                   : Yes
Format settings, Reference frames        : 2
Format settings, Reference frames        : 2 frames
Format settings, GOP                     : M=1, N=5
Format settings, Slice count             : 4
Format settings, Slice count             : 4 slices per frame
Internet media type                      : video/H264
Codec ID                                 : V_MPEG4/ISO/AVC
Codec ID/Url                             : http://ffdshow-tryout.sourceforge.net/
Duration                                 : 1402485.000000
Duration                                 : 23 min 22 s
Duration                                 : 23 min 22 s 485 ms
Duration                                 : 23 min 22 s
Duration                                 : 00:23:22.485
Duration                                 : 00:23:21:02
Duration                                 : 00:23:22.485 (00:23:21:02)
Bit rate mode                            : VBR
Bit rate mode                            : Variable
Bit rate                                 : 8372395
Bit rate                                 : 8 372 kb/s
Maximum bit rate                         : 36241408
Maximum bit rate                         : 36.2 Mb/s
Width                                    : 1920
Width                                    : 1 920 pixels
Height                                   : 1080
Height                                   : 1 080 pixels
Stored_Height                            : 1088
Sampled_Width                            : 1920
Sampled_Height                           : 1080
Pixel aspect ratio                       : 1.000
Display aspect ratio                     : 1.778
Display aspect ratio                     : 16:9
Frame rate mode                          : CFR
Frame rate mode                          : Constant
Frame rate                               : 23.976
Frame rate                               : 23.976 (24000/1001) FPS
FrameRate_Num                            : 24000
FrameRate_Den                            : 1001
Frame count                              : 33626
Color space                              : YUV
Chroma subsampling                       : 4:2:0
Chroma subsampling                       : 4:2:0
Bit depth                                : 8
Bit depth                                : 8 bits
Scan type                                : Progressive
Scan type                                : Progressive
Bits/(Pixel*Frame)                       : 0.168
Delay                                    : 0
Delay                                    : 00:00:00.000
Delay                                    : 00:00:00:00
Delay                                    : 00:00:00.000 (00:00:00:00)
Delay, origin                            : Container
Delay, origin                            : Container
Stream size                              : 1467769958
Stream size                              : 1.37 GiB (67%)
Stream size                              : 1 GiB
Stream size                              : 1.4 GiB
Stream size                              : 1.37 GiB
Stream size                              : 1.367 GiB
Stream size                              : 1.37 GiB (67%)
Proportion of this stream                : 0.67342
Default                                  : Yes
Default                                  : Yes
Forced                                   : No
Forced                                   : No
Buffer size                              : 29687808

Audio #1
Count                                    : 285
Count of stream of this kind             : 4
Kind of stream                           : Audio
Kind of stream                           : Audio
Stream identifier                        : 0
Stream identifier                        : 1
StreamOrder                              : 1
ID                                       : 2
ID                                       : 2
Unique ID                                : 11254018164315169758
Format                                   : MLP FBA
Format                                   : MLP FBA
Format/Info                              : Meridian Lossless Packing FBA
Commercial name                          : Dolby TrueHD
Commercial name                          : Dolby TrueHD
Codec ID                                 : A_TRUEHD
Codec ID/Url                             : http://www.dolby.com/consumer/technology/trueHD.html
Duration                                 : 1402485.000000
Duration                                 : 23 min 22 s
Duration                                 : 23 min 22 s 485 ms
Duration                                 : 23 min 22 s
Duration                                 : 00:23:22.485
Duration                                 : 00:23:22.485
Bit rate mode                            : VBR
Bit rate mode                            : Variable
Bit rate                                 : 2991774
Bit rate                                 : 2 992 kb/s
Maximum bit rate                         : 4359000
Maximum bit rate                         : 4 359 kb/s
Channel(s)                               : 6
Channel(s)                               : 6 channels
Channel positions                        : Front: L C R, Side: L R, LFE
Channel positions                        : 3/2/0.1
Channel layout                           : L R C LFE Ls Rs
Samples per frame                        : 40
Sampling rate                            : 48000
Sampling rate                            : 48.0 kHz
Samples count                            : 67319280
Frame rate                               : 1200.000
Frame rate                               : 1 200.000 FPS (40 SPF)
FrameRate_Num                            : 1200
FrameRate_Den                            : 1
Frame count                              : 1682982
Compression mode                         : Lossless
Compression mode                         : Lossless
Delay                                    : 0
Delay                                    : 00:00:00.000
Delay                                    : 00:00:00.000
Delay, origin                            : Container
Delay, origin                            : Container
Delay relative to video                  : 0
Delay relative to video                  : 00:00:00.000
Delay relative to video                  : 00:00:00.000
Stream size                              : 524489944
Stream size                              : 500 MiB (24%)
Stream size                              : 500 MiB
Stream size                              : 500 MiB
Stream size                              : 500 MiB
Stream size                              : 500.2 MiB
Stream size                              : 500 MiB (24%)
Proportion of this stream                : 0.24064
Title                                    : TrueHD 5.1
Language                                 : en
Language                                 : English
Language                                 : English
Language                                 : en
Language                                 : eng
Language                                 : en
Default                                  : Yes
Default                                  : Yes
Forced                                   : No
Forced                                   : No

Audio #2
Count                                    : 326
Count of stream of this kind             : 4
Kind of stream                           : Audio
Kind of stream                           : Audio
Stream identifier                        : 1
Stream identifier                        : 2
StreamOrder                              : 2
ID                                       : 3
ID                                       : 3
Unique ID                                : 10361330195630253603
Format                                   : AC-3
Format                                   : AC-3
Format/Info                              : Audio Coding 3
Format/Url                               : https://en.wikipedia.org/wiki/AC3
Commercial name                          : Dolby Digital
Commercial name                          : Dolby Digital
Format settings, Endianness              : Big
Codec ID                                 : A_AC3
Duration                                 : 1402496.000000
Duration                                 : 23 min 22 s
Duration                                 : 23 min 22 s 496 ms
Duration                                 : 23 min 22 s
Duration                                 : 00:23:22.496
Duration                                 : 00:23:22.496
Bit rate mode                            : CBR
Bit rate mode                            : Constant
Bit rate                                 : 448000
Bit rate                                 : 448 kb/s
Channel(s)                               : 6
Channel(s)                               : 6 channels
Channel positions                        : Front: L C R, Side: L R, LFE
Channel positions                        : 3/2/0.1
Channel layout                           : L R C LFE Ls Rs
Samples per frame                        : 1536
Sampling rate                            : 48000
Sampling rate                            : 48.0 kHz
Samples count                            : 67319808
Frame rate                               : 31.250
Frame rate                               : 31.250 FPS (1536 SPF)
Frame count                              : 43828
Compression mode                         : Lossy
Compression mode                         : Lossy
Delay                                    : 0
Delay                                    : 00:00:00.000
Delay                                    : 00:00:00.000
Delay, origin                            : Container
Delay, origin                            : Container
Delay relative to video                  : 0
Delay relative to video                  : 00:00:00.000
Delay relative to video                  : 00:00:00.000
Stream size                              : 78539776
Stream size                              : 74.9 MiB (4%)
Stream size                              : 75 MiB
Stream size                              : 75 MiB
Stream size                              : 74.9 MiB
Stream size                              : 74.90 MiB
Stream size                              : 74.9 MiB (4%)
Proportion of this stream                : 0.03603
Title                                    : AC-3 5.1
Language                                 : en
Language                                 : English
Language                                 : English
Language                                 : en
Language                                 : eng
Language                                 : en
Service kind                             : CM
Service kind                             : Complete Main
Default                                  : No
Default                                  : No
Forced                                   : No
Forced                                   : No
bsid                                     : 6
Dialog Normalization                     : -31
Dialog Normalization                     : -31 dB
compr                                    : -0.28
compr                                    : -0.28 dB
acmod                                    : 7
lfeon                                    : 1
cmixlev                                  : -3.0
cmixlev                                  : -3.0 dB
surmixlev                                : -3 dB
surmixlev                                : -3 dB
dmixmod                                  : Lt/Rt
ltrtcmixlev                              : -3.0
ltrtcmixlev                              : -3.0 dB
ltrtsurmixlev                            : -3.0
ltrtsurmixlev                            : -3.0 dB
lorocmixlev                              : -3.0
lorocmixlev                              : -3.0 dB
lorosurmixlev                            : -3.0
lorosurmixlev                            : -3.0 dB
dialnorm_Average                         : -31
dialnorm_Average                         : -31 dB
dialnorm_Minimum                         : -31
dialnorm_Minimum                         : -31 dB
dialnorm_Maximum                         : -31
dialnorm_Maximum                         : -31 dB
dialnorm_Count                           : 78
compr_Average                            : 0.64
compr_Average                            : 0.64 dB
compr_Minimum                            : -4.53
compr_Minimum                            : -4.53 dB
compr_Maximum                            : 2.77
compr_Maximum                            : 2.77 dB
compr_Count                              : 76
dynrng_Average                           : 0.62
dynrng_Average                           : 0.62 dB
dynrng_Minimum                           : -1.48
dynrng_Minimum                           : -1.48 dB
dynrng_Maximum                           : 2.15
dynrng_Maximum                           : 2.15 dB
dynrng_Count                             : 78

Audio #3
Count                                    : 323
Count of stream of this kind             : 4
Kind of stream                           : Audio
Kind of stream                           : Audio
Stream identifier                        : 2
Stream identifier                        : 3
StreamOrder                              : 3
ID                                       : 4
ID                                       : 4
Unique ID                                : 10319699278594842107
Format                                   : AC-3
Format                                   : AC-3
Format/Info                              : Audio Coding 3
Format/Url                               : https://en.wikipedia.org/wiki/AC3
Commercial name                          : Dolby Digital
Commercial name                          : Dolby Digital
Format settings, Endianness              : Big
Codec ID                                 : A_AC3
Duration                                 : 1402496.000000
Duration                                 : 23 min 22 s
Duration                                 : 23 min 22 s 496 ms
Duration                                 : 23 min 22 s
Duration                                 : 00:23:22.496
Duration                                 : 00:23:22.496
Bit rate mode                            : CBR
Bit rate mode                            : Constant
Bit rate                                 : 224000
Bit rate                                 : 224 kb/s
Channel(s)                               : 2
Channel(s)                               : 2 channels
Channel positions                        : Front: L R
Channel positions                        : 2/0/0
Channel layout                           : L R
Samples per frame                        : 1536
Sampling rate                            : 48000
Sampling rate                            : 48.0 kHz
Samples count                            : 67319808
Frame rate                               : 31.250
Frame rate                               : 31.250 FPS (1536 SPF)
Frame count                              : 43828
Compression mode                         : Lossy
Compression mode                         : Lossy
Delay                                    : 0
Delay                                    : 00:00:00.000
Delay                                    : 00:00:00.000
Delay, origin                            : Container
Delay, origin                            : Container
Delay relative to video                  : 0
Delay relative to video                  : 00:00:00.000
Delay relative to video                  : 00:00:00.000
Stream size                              : 39269888
Stream size                              : 37.5 MiB (2%)
Stream size                              : 37 MiB
Stream size                              : 37 MiB
Stream size                              : 37.5 MiB
Stream size                              : 37.45 MiB
Stream size                              : 37.5 MiB (2%)
Proportion of this stream                : 0.01802
Title                                    : Commentary by Creators Dan Harmon, Justin Roiland, Writer Mike McMahan, Director Juan Meza-Léon and John Mayer
Language                                 : en
Language                                 : English
Language                                 : English
Language                                 : en
Language                                 : eng
Language                                 : en
Service kind                             : CM
Service kind                             : Complete Main
Default                                  : No
Default                                  : No
Forced                                   : No
Forced                                   : No
bsid                                     : 6
Dialog Normalization                     : -31
Dialog Normalization                     : -31 dB
compr                                    : -0.28
compr                                    : -0.28 dB
dsurmod                                  : 1
dsurmod                                  : Not Dolby Surround encoded
acmod                                    : 2
lfeon                                    : 0
ltrtcmixlev                              : -3.0
ltrtcmixlev                              : -3.0 dB
ltrtsurmixlev                            : -3.0
ltrtsurmixlev                            : -3.0 dB
lorocmixlev                              : -3.0
lorocmixlev                              : -3.0 dB
lorosurmixlev                            : -3.0
lorosurmixlev                            : -3.0 dB
dialnorm_Average                         : -31
dialnorm_Average                         : -31 dB
dialnorm_Minimum                         : -31
dialnorm_Minimum                         : -31 dB
dialnorm_Maximum                         : -31
dialnorm_Maximum                         : -31 dB
dialnorm_Count                           : 78
compr_Average                            : 0.98
compr_Average                            : 0.98 dB
compr_Minimum                            : -1.80
compr_Minimum                            : -1.80 dB
compr_Maximum                            : 2.77
compr_Maximum                            : 2.77 dB
compr_Count                              : 76
dynrng_Average                           : 0.67
dynrng_Average                           : 0.67 dB
dynrng_Minimum                           : -1.16
dynrng_Minimum                           : -1.16 dB
dynrng_Maximum                           : 2.15
dynrng_Maximum                           : 2.15 dB
dynrng_Count                             : 78

Audio #4
Count                                    : 323
Count of stream of this kind             : 4
Kind of stream                           : Audio
Kind of stream                           : Audio
Stream identifier                        : 3
Stream identifier                        : 4
StreamOrder                              : 4
ID                                       : 5
ID                                       : 5
Unique ID                                : 16267354825802725600
Format                                   : AC-3
Format                                   : AC-3
Format/Info                              : Audio Coding 3
Format/Url                               : https://en.wikipedia.org/wiki/AC3
Commercial name                          : Dolby Digital
Commercial name                          : Dolby Digital
Format settings, Endianness              : Big
Codec ID                                 : A_AC3
Duration                                 : 1402496.000000
Duration                                 : 23 min 22 s
Duration                                 : 23 min 22 s 496 ms
Duration                                 : 23 min 22 s
Duration                                 : 00:23:22.496
Duration                                 : 00:23:22.496
Bit rate mode                            : CBR
Bit rate mode                            : Constant
Bit rate                                 : 224000
Bit rate                                 : 224 kb/s
Channel(s)                               : 2
Channel(s)                               : 2 channels
Channel positions                        : Front: L R
Channel positions                        : 2/0/0
Channel layout                           : L R
Samples per frame                        : 1536
Sampling rate                            : 48000
Sampling rate                            : 48.0 kHz
Samples count                            : 67319808
Frame rate                               : 31.250
Frame rate                               : 31.250 FPS (1536 SPF)
Frame count                              : 43828
Compression mode                         : Lossy
Compression mode                         : Lossy
Delay                                    : 0
Delay                                    : 00:00:00.000
Delay                                    : 00:00:00.000
Delay, origin                            : Container
Delay, origin                            : Container
Delay relative to video                  : 0
Delay relative to video                  : 00:00:00.000
Delay relative to video                  : 00:00:00.000
Stream size                              : 39269888
Stream size                              : 37.5 MiB (2%)
Stream size                              : 37 MiB
Stream size                              : 37 MiB
Stream size                              : 37.5 MiB
Stream size                              : 37.45 MiB
Stream size                              : 37.5 MiB (2%)
Proportion of this stream                : 0.01802
Title                                    : Commentary by Guests Courtney Love and Marilyn Manson
Language                                 : en
Language                                 : English
Language                                 : English
Language                                 : en
Language                                 : eng
Language                                 : en
Service kind                             : CM
Service kind                             : Complete Main
Default                                  : No
Default                                  : No
Forced                                   : No
Forced                                   : No
bsid                                     : 6
Dialog Normalization                     : -31
Dialog Normalization                     : -31 dB
compr                                    : -0.28
compr                                    : -0.28 dB
dsurmod                                  : 1
dsurmod                                  : Not Dolby Surround encoded
acmod                                    : 2
lfeon                                    : 0
ltrtcmixlev                              : -3.0
ltrtcmixlev                              : -3.0 dB
ltrtsurmixlev                            : -3.0
ltrtsurmixlev                            : -3.0 dB
lorocmixlev                              : -3.0
lorocmixlev                              : -3.0 dB
lorosurmixlev                            : -3.0
lorosurmixlev                            : -3.0 dB
dialnorm_Average                         : -31
dialnorm_Average                         : -31 dB
dialnorm_Minimum                         : -31
dialnorm_Minimum                         : -31 dB
dialnorm_Maximum                         : -31
dialnorm_Maximum                         : -31 dB
dialnorm_Count                           : 78
compr_Average                            : 0.95
compr_Average                            : 0.95 dB
compr_Minimum                            : -1.80
compr_Minimum                            : -1.80 dB
compr_Maximum                            : 2.77
compr_Maximum                            : 2.77 dB
compr_Count                              : 76
dynrng_Average                           : 0.62
dynrng_Average                           : 0.62 dB
dynrng_Minimum                           : -1.48
dynrng_Minimum                           : -1.48 dB
dynrng_Maximum                           : 2.15
dynrng_Maximum                           : 2.15 dB
dynrng_Count                             : 78

Text
Count                                    : 304
Count of stream of this kind             : 1
Kind of stream                           : Text
Kind of stream                           : Text
Stream identifier                        : 0
StreamOrder                              : 5
ID                                       : 6
ID                                       : 6
Unique ID                                : 10651012613879145588
Format                                   : PGS
Format                                   : PGS
Commercial name                          : PGS
Codec ID                                 : S_HDMV/PGS
Codec ID/Info                            : Picture based subtitle format used on BDs/HD-DVDs
Duration                                 : 1392600.000000
Duration                                 : 23 min 12 s
Duration                                 : 23 min 12 s 600 ms
Duration                                 : 23 min 12 s
Duration                                 : 00:23:12.600
Duration                                 : 00:21:23
Duration                                 : 00:23:12.600 (00:21:23)
Bit rate                                 : 103042
Bit rate                                 : 103 kb/s
Frame rate                               : 0.921
Frame rate                               : 0.921 FPS
Frame count                              : 1282
Count of elements                        : 1282
Stream size                              : 17937038
Stream size                              : 17.1 MiB (1%)
Stream size                              : 17 MiB
Stream size                              : 17 MiB
Stream size                              : 17.1 MiB
Stream size                              : 17.11 MiB
Stream size                              : 17.1 MiB (1%)
Proportion of this stream                : 0.00823
Title                                    : English (SDH)
Language                                 : en
Language                                 : English
Language                                 : English
Language                                 : en
Language                                 : eng
Language                                 : en
Default                                  : No
Default                                  : No
Forced                                   : No
Forced                                   : No

Menu
Count                                    : 106
Count of stream of this kind             : 1
Kind of stream                           : Menu
Kind of stream                           : Menu
Stream identifier                        : 0
Chapters_Pos_Begin                       : 101
Chapters_Pos_End                         : 106
00:00:00.000                             : en:Chapter 01
00:01:23.000                             : en:Chapter 02
00:01:54.823                             : en:Chapter 03
00:09:55.887                             : en:Chapter 04
00:22:13.874                             : en:Chapter 05
"""
# fmt: on

EXAMPLE_SEARCH_PAYLOAD = MediaSearchPayload(
    media_type=MediaType.SERIES,
    imdb_id="tt2861424",
    tmdb_id="60625",
    tmdb_data={
        "adult": False,
        "backdrop_path": "/Ao5pBFuWY32cVuh6iYjEjZMEscN.jpg",
        "created_by": [
            {
                "id": 57194,
                "credit_id": "57bf826fc3a3684d25001b3c",
                "name": "Dan Harmon",
                "original_name": "Dan Harmon",
                "gender": 2,
                "profile_path": "/gDwFosoyPTd0pmnKParzGj3kaMg.jpg",
            },
            {
                "id": 1245733,
                "credit_id": "57bf827dc3a3684d3400183e",
                "name": "Justin Roiland",
                "original_name": "Justin Roiland",
                "gender": 2,
                "profile_path": "/wYApP38aXe6ZcEtlBAfNRxJTQQi.jpg",
            },
        ],
        "episode_run_time": [22],
        "first_air_date": "2013-12-02",
        "genres": [
            {"id": 16, "name": "Animation"},
            {"id": 35, "name": "Comedy"},
            {"id": 10765, "name": "Sci-Fi & Fantasy"},
            {"id": 10759, "name": "Action & Adventure"},
        ],
        "id": 60625,
        "in_production": True,
        "languages": ["en"],
        "last_air_date": "2025-07-27",
        "last_episode_to_air": {
            "id": 6122210,
            "name": "Random Title Name",
            "overview": "Some random overview.",
            "vote_average": 9.409,
            "vote_count": 11,
            "air_date": "2025-07-27",
            "episode_number": 10,
            "episode_type": "finale",
            "production_code": "",
            "runtime": 24,
            "season_number": 8,
            "show_id": 60625,
            "still_path": "/qwfGBFu2QrPm1BrkvSb9TNRXwXm.jpg",
        },
        "name": "Series Name",
        "next_episode_to_air": None,
        "networks": [
            {
                "id": 80,
                "logo_path": "/tHZPHOLc6iF27G34cAZGPsMtMSy.png",
                "name": "",
                "origin_country": "US",
            }
        ],
        "number_of_episodes": 81,
        "number_of_seasons": 8,
        "origin_country": ["US"],
        "original_language": "en",
        "original_name": "Series Name",
        "overview": "Some episode overview.",
        "popularity": 69.9073,
        "poster_path": "/WGRQ8FpjkDTzivQJ43t94bOuY0.jpg",
        "production_companies": [
            {
                "id": 6760,
                "logo_path": "/h3syDHowNmk61FzlW2GPY0vJCFh.png",
                "name": "Williams Street",
                "origin_country": "US",
            },
            {
                "id": 8300,
                "logo_path": None,
                "name": "Harmonious Claptrap",
                "origin_country": "US",
            },
            {
                "id": 47394,
                "logo_path": None,
                "name": "Justin Roiland's Solo Vanity Card Productions",
                "origin_country": "US",
            },
            {
                "id": 32542,
                "logo_path": None,
                "name": "Starburns Industries",
                "origin_country": "US",
            },
            {
                "id": 131124,
                "logo_path": None,
                "name": "Green Portal Productions",
                "origin_country": "US",
            },
        ],
        "production_countries": [
            {"iso_3166_1": "US", "name": "United States of America"}
        ],
        "seasons": [
            {
                "air_date": "2016-10-24",
                "episode_count": 36,
                "id": 106178,
                "name": "Specials",
                "overview": "",
                "poster_path": "/3my0MrOKCSYMw8VfLiiM9k00bdF.jpg",
                "season_number": 0,
                "vote_average": 0.0,
            },
            {
                "air_date": "2013-12-02",
                "episode_count": 11,
                "id": 60059,
                "name": "Season 1",
                "overview": "",
                "poster_path": "/8BXUZ0nnR3DZsf30DYMFHfuTxxi.jpg",
                "season_number": 1,
                "vote_average": 8.0,
            },
            {
                "air_date": "2015-07-26",
                "episode_count": 10,
                "id": 66738,
                "name": "Season 2",
                "overview": "",
                "poster_path": "/xcYamBmQmSCpl9L1B5ihesnR1Gb.jpg",
                "season_number": 2,
                "vote_average": 8.3,
            },
            {
                "air_date": "2017-04-01",
                "episode_count": 10,
                "id": 86926,
                "name": "Season 3",
                "overview": "",
                "poster_path": "/rX55zDxWkNuG4wyQyfMBkSk75df.jpg",
                "season_number": 3,
                "vote_average": 8.3,
            },
            {
                "air_date": "2019-11-10",
                "episode_count": 10,
                "id": 128112,
                "name": "Season 4",
                "overview": "",
                "poster_path": "/87abbwoOfm5MMCWoFewN8pNGZxW.jpg",
                "season_number": 4,
                "vote_average": 7.9,
            },
            {
                "air_date": "2021-06-20",
                "episode_count": 10,
                "id": 188470,
                "name": "Season 5",
                "overview": "",
                "poster_path": "/8KdHdOAP8mM4TmykkXnpr6qkyUU.jpg",
                "season_number": 5,
                "vote_average": 7.3,
            },
            {
                "air_date": "2022-09-04",
                "episode_count": 10,
                "id": 302503,
                "name": "Season 6",
                "overview": "",
                "poster_path": "/cvhNj9eoRBe5SxjCbQTkh05UP5K.jpg",
                "season_number": 6,
                "vote_average": 7.6,
            },
            {
                "air_date": "2023-10-15",
                "episode_count": 10,
                "id": 354041,
                "name": "Season 7",
                "overview": "",
                "poster_path": "/7Dgz3xehPaQv5XpQ39WHBivJDSW.jpg",
                "season_number": 7,
                "vote_average": 7.3,
            },
            {
                "air_date": "2025-05-25",
                "episode_count": 10,
                "id": 424080,
                "name": "Season 8",
                "overview": "",
                "poster_path": "/WGRQ8FpjkDTzivQJ43t94bOuY0.jpg",
                "season_number": 8,
                "vote_average": 8.2,
            },
        ],
        "spoken_languages": [
            {"english_name": "English", "iso_639_1": "en", "name": "English"}
        ],
        "status": "Returning Series",
        "tagline": "Science makes sense, family doesn't.",
        "type": "Scripted",
        "vote_average": 8.689,
        "vote_count": 10357,
        "alternative_titles": {
            "results": [
                {"iso_3166_1": "US", "title": "Some Alt Title", "type": "webisodes"},
                {
                    "iso_3166_1": "US",
                    "title": "Some Alt Title",
                    "type": "webisodes",
                },
            ]
        },
        "images": {
            "backdrops": [
                {
                    "aspect_ratio": 1.778,
                    "height": 1080,
                    "iso_639_1": "en",
                    "file_path": "/v5An18JSiuBJiULS6x3EUIdOuvC.jpg",
                    "vote_average": 3.334,
                    "vote_count": 1,
                    "width": 1920,
                }
            ],
            "logos": [
                {
                    "aspect_ratio": 3.097,
                    "height": 1299,
                    "iso_639_1": "en",
                    "file_path": "/wq3wqFLwwqnhG6DxmSji9ehLcx6.png",
                    "vote_average": 10.0,
                    "vote_count": 4,
                    "width": 4023,
                },
            ],
        },
        "external_ids": {
            "imdb_id": "tt2861424",
            "freebase_mid": "/m/0z6p24j",
            "freebase_id": None,
            "tvdb_id": 275274,
            "tvrage_id": 33381,
            "wikidata_id": "Q15659308",
            "facebook_id": "",
            "instagram_id": "",
            "twitter_id": "",
        },
    },
    tvdb_id="275274",
    tvdb_data={
        "series": {
            "id": 275274,
            "name": "Series Name",
            "slug": "series-name-slug",
            "image": "https://artworks.thetvdb.com/banners/posters/275274-2.jpg",
            "nameTranslations": [
                "ces",
                "dan",
                "deu",
                "eng",
            ],
            "overviewTranslations": [
                "ces",
                "dan",
                "deu",
                "eng",
            ],
            "firstAired": "2013-12-02",
            "lastAired": "2025-07-27",
            "nextAired": "",
            "score": 3406176,
            "status": {
                "id": None,
                "name": None,
                "recordType": "",
                "keepUpdated": False,
            },
            "originalCountry": "usa",
            "originalLanguage": "eng",
            "defaultSeasonType": 1,
            "isOrderRandomized": False,
            "lastUpdated": "2025-08-18 18:05:26",
            "averageRuntime": 22,
            "episodes": None,
            "overview": "Series Name Overview...",
            "year": current_year,
        }
    },
    anilist_id=None,
    anilist_data=None,
    mal_id=None,
    title="Series Name",
    year=2013,
    original_title=None,
)
