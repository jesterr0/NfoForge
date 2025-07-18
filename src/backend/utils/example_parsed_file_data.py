from pymediainfo import MediaInfo
from src.payloads.media_search import MediaSearchPayload
from datetime import datetime

current_year = datetime.now().year

EXAMPLE_FILE_NAME = f"Movie.Name.{current_year}.Directors.Cut.IMAX.REPACK.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.HYBRID.REMUX-SomeGroup.mkv"

_EXAMPLE_MEDIAINFO_XML_DATA = f"""\
<Mediainfo version="23.10">
<File>
<track type="General">
<Count>351</Count>
<Count_of_stream_of_this_kind>1</Count_of_stream_of_this_kind>
<Kind_of_stream>General</Kind_of_stream>
<Kind_of_stream>General</Kind_of_stream>
<Stream_identifier>0</Stream_identifier>
<Unique_ID>72016458352865119504084926981396730566</Unique_ID>
<Unique_ID>72016458352865119504084926981396730566 (0x362DDD886EE76435518FF5DA845A32C0)</Unique_ID>
<Count_of_video_streams>1</Count_of_video_streams>
<Count_of_audio_streams>2</Count_of_audio_streams>
<Count_of_text_streams>16</Count_of_text_streams>
<Count_of_menu_streams>1</Count_of_menu_streams>
<Video_Format_List>HEVC</Video_Format_List>
<Video_Format_WithHint_List>HEVC</Video_Format_WithHint_List>
<Codecs_Video>HEVC</Codecs_Video>
<Audio_Format_List>MLP FBA 16-ch / AC-3</Audio_Format_List>
<Audio_Format_WithHint_List>MLP FBA 16-ch / AC-3</Audio_Format_WithHint_List>
<Audio_codecs>MLP FBA 16-ch / AC-3</Audio_codecs>
<Audio_Language_List>English / English</Audio_Language_List>
<Audio_Channels_Total>14</Audio_Channels_Total>
<Text_Format_List>PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS</Text_Format_List>
<Text_Format_WithHint_List>PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS</Text_Format_WithHint_List>
<Text_codecs>PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS</Text_codecs>
<Text_Language_List>English / English / Czech / Danish / Dutch / Finnish / French / French / German / Italian / Japanese / Norwegian / Polish / Spanish / Spanish / Swedish</Text_Language_List>
<Complete_name>/some_path/Movie.Name.{current_year}.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.HYBRID.REMUX-SomeGroup/Movie.Name.{current_year}.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.HYBRID.REMUX-SomeGroup.mkv</Complete_name>
<Folder_name>/some_path/Movie.Name.{current_year}.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.HYBRID.REMUX-SomeGroup</Folder_name>
<File_name_extension>Movie.Name.{current_year}.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.HYBRID.REMUX-SomeGroup.mkv</File_name_extension>
<File_name>Movie.Name.{current_year}.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.HYBRID.REMUX-SomeGroup</File_name>
<File_extension>mkv</File_extension>
<Format>Matroska</Format>
<Format>Matroska</Format>
<Format_Url>https://matroska.org/downloads/windows.html</Format_Url>
<Format_Extensions_usually_used>mkv mk3d mka mks</Format_Extensions_usually_used>
<Commercial_name>Matroska</Commercial_name>
<Format_version>Version 4</Format_version>
<File_size>51013759049</File_size>
<File_size>47.5 GiB</File_size>
<File_size>48 GiB</File_size>
<File_size>48 GiB</File_size>
<File_size>47.5 GiB</File_size>
<File_size>47.51 GiB</File_size>
<Duration>6898624</Duration>
<Duration>1 h 54 min</Duration>
<Duration>1 h 54 min 58 s 624 ms</Duration>
<Duration>1 h 54 min</Duration>
<Duration>01:54:58.624</Duration>
<Duration>01:55:00;09</Duration>
<Duration>01:54:58.624 (01:55:00;09)</Duration>
<Overall_bit_rate_mode>VBR</Overall_bit_rate_mode>
<Overall_bit_rate_mode>Variable</Overall_bit_rate_mode>
<Overall_bit_rate>59158185</Overall_bit_rate>
<Overall_bit_rate>59.2 Mb/s</Overall_bit_rate>
<Frame_rate>23.976</Frame_rate>
<Frame_rate>23.976 FPS</Frame_rate>
<Frame_count>165401</Frame_count>
<Stream_size>61820330</Stream_size>
<Stream_size>59.0 MiB (0%)</Stream_size>
<Stream_size>59 MiB</Stream_size>
<Stream_size>59 MiB</Stream_size>
<Stream_size>59.0 MiB</Stream_size>
<Stream_size>58.96 MiB</Stream_size>
<Stream_size>59.0 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00121</Proportion_of_this_stream>
<IsStreamable>Yes</IsStreamable>
<Title>Movie Name ({current_year})</Title>
<Movie_name>Movie Name ({current_year})</Movie_name>
<Encoded_date>2022-08-30 09:36:09 UTC</Encoded_date>
<File_creation_date>2025-02-15 04:27:46.480 UTC</File_creation_date>
<File_creation_date__local_>2025-02-14 23:27:46.480</File_creation_date__local_>
<File_last_modification_date>2025-02-15 04:59:16.866 UTC</File_last_modification_date>
<File_last_modification_date__local_>2025-02-14 23:59:16.866</File_last_modification_date__local_>
<Writing_application>mkvmerge v70.0.0 ('Caught A Lite Sneeze') 64-bit</Writing_application>
<Writing_application>mkvmerge v70.0.0 ('Caught A Lite Sneeze') 64-bit</Writing_application>
<Writing_library>libebml v1.4.2 + libmatroska v1.6.4</Writing_library>
<Writing_library>libebml v1.4.2 + libmatroska v1.6.4</Writing_library>
<IMDB>tt6264654</IMDB>
<TMDB>movie/550988</TMDB>
</track>
<track type="Video">
<Count>381</Count>
<Count_of_stream_of_this_kind>1</Count_of_stream_of_this_kind>
<Kind_of_stream>Video</Kind_of_stream>
<Kind_of_stream>Video</Kind_of_stream>
<Stream_identifier>0</Stream_identifier>
<StreamOrder>0</StreamOrder>
<ID>1</ID>
<ID>1</ID>
<Unique_ID>12437146302198571983</Unique_ID>
<Format>HEVC</Format>
<Format>HEVC</Format>
<Format_Info>High Efficiency Video Coding</Format_Info>
<Format_Url>http://www.itu.int</Format_Url>
<Commercial_name>HEVC</Commercial_name>
<Format_profile>Main 10@L5.1@High</Format_profile>
<HDR_format>Dolby Vision / SMPTE ST 2086</HDR_format>
<HDR_format>Dolby Vision, Version 1.0, dvhe.08.06, BL+RPU, HDR10 compatible / SMPTE ST 2086, HDR10 compatible</HDR_format>
<HDR_Format_Commercial>HDR10 / HDR10</HDR_Format_Commercial>
<HDR_Format_Version>1.0 / </HDR_Format_Version>
<HDR_Format_Profile>dvhe.08 / </HDR_Format_Profile>
<HDR_Format_Level>06 / </HDR_Format_Level>
<HDR_Format_Settings>BL+RPU / </HDR_Format_Settings>
<HDR_Format_Compatibility>HDR10 / HDR10</HDR_Format_Compatibility>
<Internet_media_type>video/H265</Internet_media_type>
<Codec_ID>V_MPEGH/ISO/HEVC</Codec_ID>
<Duration>6898600.000000</Duration>
<Duration>1 h 54 min</Duration>
<Duration>1 h 54 min 58 s 600 ms</Duration>
<Duration>1 h 54 min</Duration>
<Duration>01:54:58.600</Duration>
<Duration>01:55:00;09</Duration>
<Duration>01:54:58.600 (01:55:00;09)</Duration>
<Bit_rate>49960501</Bit_rate>
<Bit_rate>50.0 Mb/s</Bit_rate>
<Width>3840</Width>
<Width>3 840 pixels</Width>
<Height>2160</Height>
<Height>2 160 pixels</Height>
<Sampled_Width>3840</Sampled_Width>
<Sampled_Height>2160</Sampled_Height>
<Pixel_aspect_ratio>1.000</Pixel_aspect_ratio>
<Display_aspect_ratio>1.778</Display_aspect_ratio>
<Display_aspect_ratio>16:9</Display_aspect_ratio>
<Frame_rate_mode>CFR</Frame_rate_mode>
<Frame_rate_mode>Constant</Frame_rate_mode>
<Frame_rate>23.976</Frame_rate>
<Frame_rate>23.976 (24000/1001) FPS</Frame_rate>
<FrameRate_Num>24000</FrameRate_Num>
<FrameRate_Den>1001</FrameRate_Den>
<Frame_count>165401</Frame_count>
<Color_space>YUV</Color_space>
<Chroma_subsampling>4:2:0</Chroma_subsampling>
<Chroma_subsampling>4:2:0 (Type 2)</Chroma_subsampling>
<ChromaSubsampling_Position>Type 2</ChromaSubsampling_Position>
<Bit_depth>10</Bit_depth>
<Bit_depth>10 bits</Bit_depth>
<Bits__Pixel_Frame_>0.251</Bits__Pixel_Frame_>
<Delay>0</Delay>
<Delay>00:00:00.000</Delay>
<Delay>00:00:00;00</Delay>
<Delay>00:00:00.000 (00:00:00;00)</Delay>
<Delay__origin>Container</Delay__origin>
<Delay__origin>Container</Delay__origin>
<Stream_size>43082189302</Stream_size>
<Stream_size>40.1 GiB (84%)</Stream_size>
<Stream_size>40 GiB</Stream_size>
<Stream_size>40 GiB</Stream_size>
<Stream_size>40.1 GiB</Stream_size>
<Stream_size>40.12 GiB</Stream_size>
<Stream_size>40.1 GiB (84%)</Stream_size>
<Proportion_of_this_stream>0.84452</Proportion_of_this_stream>
<Writing_library>ATEME Titan File 3.9.6 (4.9.6.2)        </Writing_library>
<Writing_library>ATEME Titan File 3.9.6 (4.9.6.2)        </Writing_library>
<Encoded_Library_Name>ATEME Titan File</Encoded_Library_Name>
<Encoded_Library_Version>3.9.6 (4.9.6.2)        </Encoded_Library_Version>
<Default>Yes</Default>
<Default>Yes</Default>
<Forced>No</Forced>
<Forced>No</Forced>
<colour_description_present>Yes</colour_description_present>
<colour_description_present_Source>Stream</colour_description_present_Source>
<Color_range>Limited</Color_range>
<colour_range_Source>Stream</colour_range_Source>
<Color_primaries>BT.2020</Color_primaries>
<colour_primaries_Source>Stream</colour_primaries_Source>
<Transfer_characteristics>PQ</Transfer_characteristics>
<transfer_characteristics_Source>Stream</transfer_characteristics_Source>
<Matrix_coefficients>BT.2020 non-constant</Matrix_coefficients>
<matrix_coefficients_Source>Stream</matrix_coefficients_Source>
<Mastering_display_color_primaries>Display P3</Mastering_display_color_primaries>
<MasteringDisplay_ColorPrimaries_Source>Stream</MasteringDisplay_ColorPrimaries_Source>
<Mastering_display_luminance>min: 0.0050 cd/m2, max: 1000 cd/m2</Mastering_display_luminance>
<MasteringDisplay_Luminance_Source>Stream</MasteringDisplay_Luminance_Source>
</track>
<track type="Audio" typeorder="1">
<Count>289</Count>
<Count_of_stream_of_this_kind>2</Count_of_stream_of_this_kind>
<Kind_of_stream>Audio</Kind_of_stream>
<Kind_of_stream>Audio</Kind_of_stream>
<Stream_identifier>0</Stream_identifier>
<Stream_identifier>1</Stream_identifier>
<StreamOrder>1</StreamOrder>
<ID>2</ID>
<ID>2</ID>
<Unique_ID>2164772528079252818</Unique_ID>
<Format>MLP FBA</Format>
<Format>MLP FBA 16-ch</Format>
<Format_Info>Meridian Lossless Packing FBA with 16-channel presentation</Format_Info>
<Commercial_name>Dolby TrueHD with Dolby Atmos</Commercial_name>
<Commercial_name>Dolby TrueHD with Dolby Atmos</Commercial_name>
<Format_AdditionalFeatures>16-ch</Format_AdditionalFeatures>
<Codec_ID>A_TRUEHD</Codec_ID>
<Codec_ID_Url>http://www.dolby.com/consumer/technology/trueHD.html</Codec_ID_Url>
<Duration>6898600.000000</Duration>
<Duration>1 h 54 min</Duration>
<Duration>1 h 54 min 58 s 600 ms</Duration>
<Duration>1 h 54 min</Duration>
<Duration>01:54:58.600</Duration>
<Duration>01:54:58.600</Duration>
<Bit_rate_mode>VBR</Bit_rate_mode>
<Bit_rate_mode>Variable</Bit_rate_mode>
<Bit_rate>7912031</Bit_rate>
<Bit_rate>7 912 kb/s</Bit_rate>
<Maximum_bit_rate>12942000</Maximum_bit_rate>
<Maximum_bit_rate>12.9 Mb/s</Maximum_bit_rate>
<Channel_s_>8</Channel_s_>
<Channel_s_>8 channels</Channel_s_>
<Channel_positions>Front: L C R, Side: L R, Back: L R, LFE</Channel_positions>
<Channel_positions>3/2/2.1</Channel_positions>
<Channel_layout>L R C LFE Ls Rs Lb Rb</Channel_layout>
<Samples_per_frame>40</Samples_per_frame>
<Sampling_rate>48000</Sampling_rate>
<Sampling_rate>48.0 kHz</Sampling_rate>
<Samples_count>331132800</Samples_count>
<Frame_rate>1200.000</Frame_rate>
<Frame_rate>1 200.000 FPS (40 SPF)</Frame_rate>
<FrameRate_Num>1200</FrameRate_Num>
<FrameRate_Den>1</FrameRate_Den>
<Frame_count>8278320</Frame_count>
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
<Stream_size>6822742600</Stream_size>
<Stream_size>6.35 GiB (13%)</Stream_size>
<Stream_size>6 GiB</Stream_size>
<Stream_size>6.4 GiB</Stream_size>
<Stream_size>6.35 GiB</Stream_size>
<Stream_size>6.354 GiB</Stream_size>
<Stream_size>6.35 GiB (13%)</Stream_size>
<Proportion_of_this_stream>0.13374</Proportion_of_this_stream>
<Title>TrueHD Atmos 7.1</Title>
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
<Number_of_dynamic_objects>13</Number_of_dynamic_objects>
<Bed_channel_count>1</Bed_channel_count>
<Bed_channel_count>1 channel</Bed_channel_count>
<Bed_channel_configuration>LFE</Bed_channel_configuration>
</track>
<track type="Audio" typeorder="2">
<Count>313</Count>
<Count_of_stream_of_this_kind>2</Count_of_stream_of_this_kind>
<Kind_of_stream>Audio</Kind_of_stream>
<Kind_of_stream>Audio</Kind_of_stream>
<Stream_identifier>1</Stream_identifier>
<Stream_identifier>2</Stream_identifier>
<StreamOrder>2</StreamOrder>
<ID>3</ID>
<ID>3</ID>
<Unique_ID>7017140953773492237</Unique_ID>
<Format>AC-3</Format>
<Format>AC-3</Format>
<Format_Info>Audio Coding 3</Format_Info>
<Format_Url>https://en.wikipedia.org/wiki/AC3</Format_Url>
<Commercial_name>Dolby Digital</Commercial_name>
<Commercial_name>Dolby Digital</Commercial_name>
<Format_settings__Endianness>Big</Format_settings__Endianness>
<Codec_ID>A_AC3</Codec_ID>
<Duration>6898624.000000</Duration>
<Duration>1 h 54 min</Duration>
<Duration>1 h 54 min 58 s 624 ms</Duration>
<Duration>1 h 54 min</Duration>
<Duration>01:54:58.624</Duration>
<Duration>01:54:58.624</Duration>
<Bit_rate_mode>CBR</Bit_rate_mode>
<Bit_rate_mode>Constant</Bit_rate_mode>
<Bit_rate>640000</Bit_rate>
<Bit_rate>640 kb/s</Bit_rate>
<Channel_s_>6</Channel_s_>
<Channel_s_>6 channels</Channel_s_>
<Channel_positions>Front: L C R, Side: L R, LFE</Channel_positions>
<Channel_positions>3/2/0.1</Channel_positions>
<Channel_layout>L R C LFE Ls Rs</Channel_layout>
<Samples_per_frame>1536</Samples_per_frame>
<Sampling_rate>48000</Sampling_rate>
<Sampling_rate>48.0 kHz</Sampling_rate>
<Samples_count>331133952</Samples_count>
<Frame_rate>31.250</Frame_rate>
<Frame_rate>31.250 FPS (1536 SPF)</Frame_rate>
<Frame_count>215582</Frame_count>
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
<Stream_size>551889920</Stream_size>
<Stream_size>526 MiB (1%)</Stream_size>
<Stream_size>526 MiB</Stream_size>
<Stream_size>526 MiB</Stream_size>
<Stream_size>526 MiB</Stream_size>
<Stream_size>526.3 MiB</Stream_size>
<Stream_size>526 MiB (1%)</Stream_size>
<Proportion_of_this_stream>0.01082</Proportion_of_this_stream>
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
<dialnorm_Average>-31</dialnorm_Average>
<dialnorm_Average>-31 dB</dialnorm_Average>
<dialnorm_Minimum>-31</dialnorm_Minimum>
<dialnorm_Minimum>-31 dB</dialnorm_Minimum>
<dialnorm_Maximum>-31</dialnorm_Maximum>
<dialnorm_Maximum>-31 dB</dialnorm_Maximum>
<dialnorm_Count>247</dialnorm_Count>
<compr_Average>1.77</compr_Average>
<compr_Average>1.77 dB</compr_Average>
<compr_Minimum>0.53</compr_Minimum>
<compr_Minimum>0.53 dB</compr_Minimum>
<compr_Maximum>3.15</compr_Maximum>
<compr_Maximum>3.15 dB</compr_Maximum>
<compr_Count>77</compr_Count>
<dynrng_Average>0.47</dynrng_Average>
<dynrng_Average>0.47 dB</dynrng_Average>
<dynrng_Minimum>0.00</dynrng_Minimum>
<dynrng_Minimum>0.00 dB</dynrng_Minimum>
<dynrng_Maximum>2.57</dynrng_Maximum>
<dynrng_Maximum>2.57 dB</dynrng_Maximum>
<dynrng_Count>247</dynrng_Count>
</track>
<track type="Text" typeorder="1">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>0</Stream_identifier>
<Stream_identifier>1</Stream_identifier>
<StreamOrder>3</StreamOrder>
<ID>4</ID>
<ID>4</ID>
<Unique_ID>15030197436603000446</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>13597.000000</Duration>
<Duration>13 s 597 ms</Duration>
<Duration>13 s 597 ms</Duration>
<Duration>13 s 597 ms</Duration>
<Duration>00:00:13.597</Duration>
<Duration>00:00:12</Duration>
<Duration>00:00:13.597 (00:00:12)</Duration>
<Bit_rate>64220</Bit_rate>
<Bit_rate>64.2 kb/s</Bit_rate>
<Frame_rate>0.883</Frame_rate>
<Frame_rate>0.883 FPS</Frame_rate>
<Frame_count>12</Frame_count>
<Count_of_elements>12</Count_of_elements>
<Stream_size>109150</Stream_size>
<Stream_size>107 KiB (0%)</Stream_size>
<Stream_size>107 KiB</Stream_size>
<Stream_size>107 KiB</Stream_size>
<Stream_size>107 KiB</Stream_size>
<Stream_size>106.6 KiB</Stream_size>
<Stream_size>107 KiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00000</Proportion_of_this_stream>
<Title>English (Forced)</Title>
<Language>en</Language>
<Language>English</Language>
<Language>English</Language>
<Language>en</Language>
<Language>eng</Language>
<Language>en</Language>
<Default>Yes</Default>
<Default>Yes</Default>
<Forced>Yes</Forced>
<Forced>Yes</Forced>
</track>
<track type="Text" typeorder="2">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>1</Stream_identifier>
<Stream_identifier>2</Stream_identifier>
<StreamOrder>4</StreamOrder>
<ID>5</ID>
<ID>5</ID>
<Unique_ID>850369776613837289</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>6333578.000000</Duration>
<Duration>1 h 45 min</Duration>
<Duration>1 h 45 min 33 s 578 ms</Duration>
<Duration>1 h 45 min</Duration>
<Duration>01:45:33.578</Duration>
<Duration>01:11:09</Duration>
<Duration>01:45:33.578 (01:11:09)</Duration>
<Bit_rate>57706</Bit_rate>
<Bit_rate>57.7 kb/s</Bit_rate>
<Frame_rate>0.674</Frame_rate>
<Frame_rate>0.674 FPS</Frame_rate>
<Frame_count>4270</Frame_count>
<Count_of_elements>4270</Count_of_elements>
<Stream_size>45686339</Stream_size>
<Stream_size>43.6 MiB (0%)</Stream_size>
<Stream_size>44 MiB</Stream_size>
<Stream_size>44 MiB</Stream_size>
<Stream_size>43.6 MiB</Stream_size>
<Stream_size>43.57 MiB</Stream_size>
<Stream_size>43.6 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00090</Proportion_of_this_stream>
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
<track type="Text" typeorder="3">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>2</Stream_identifier>
<Stream_identifier>3</Stream_identifier>
<StreamOrder>5</StreamOrder>
<ID>6</ID>
<ID>6</ID>
<Unique_ID>17430780143545358465</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>6835370.000000</Duration>
<Duration>1 h 53 min</Duration>
<Duration>1 h 53 min 55 s 370 ms</Duration>
<Duration>1 h 53 min</Duration>
<Duration>01:53:55.370</Duration>
<Duration>01:02:39</Duration>
<Duration>01:53:55.370 (01:02:39)</Duration>
<Bit_rate>36792</Bit_rate>
<Bit_rate>36.8 kb/s</Bit_rate>
<Frame_rate>0.550</Frame_rate>
<Frame_rate>0.550 FPS</Frame_rate>
<Frame_count>3758</Frame_count>
<Count_of_elements>3758</Count_of_elements>
<Stream_size>31436688</Stream_size>
<Stream_size>30.0 MiB (0%)</Stream_size>
<Stream_size>30 MiB</Stream_size>
<Stream_size>30 MiB</Stream_size>
<Stream_size>30.0 MiB</Stream_size>
<Stream_size>29.98 MiB</Stream_size>
<Stream_size>30.0 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00062</Proportion_of_this_stream>
<Title>Czech</Title>
<Language>cs</Language>
<Language>Czech</Language>
<Language>Czech</Language>
<Language>cs</Language>
<Language>ces</Language>
<Language>cs</Language>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Text" typeorder="4">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>3</Stream_identifier>
<Stream_identifier>4</Stream_identifier>
<StreamOrder>6</StreamOrder>
<ID>7</ID>
<ID>7</ID>
<Unique_ID>4530733467076602432</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>6835370.000000</Duration>
<Duration>1 h 53 min</Duration>
<Duration>1 h 53 min 55 s 370 ms</Duration>
<Duration>1 h 53 min</Duration>
<Duration>01:53:55.370</Duration>
<Duration>01:53:55.370</Duration>
<Bit_rate>34054</Bit_rate>
<Bit_rate>34.1 kb/s</Bit_rate>
<Frame_rate>0.336</Frame_rate>
<Frame_rate>0.336 FPS</Frame_rate>
<Frame_count>2300</Frame_count>
<Count_of_elements>2300</Count_of_elements>
<Stream_size>29096954</Stream_size>
<Stream_size>27.7 MiB (0%)</Stream_size>
<Stream_size>28 MiB</Stream_size>
<Stream_size>28 MiB</Stream_size>
<Stream_size>27.7 MiB</Stream_size>
<Stream_size>27.75 MiB</Stream_size>
<Stream_size>27.7 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00057</Proportion_of_this_stream>
<Title>Danish</Title>
<Language>da</Language>
<Language>Danish</Language>
<Language>Danish</Language>
<Language>da</Language>
<Language>dan</Language>
<Language>da</Language>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Text" typeorder="5">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>4</Stream_identifier>
<Stream_identifier>5</Stream_identifier>
<StreamOrder>7</StreamOrder>
<ID>8</ID>
<ID>8</ID>
<Unique_ID>13393963019490599196</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>6835495.000000</Duration>
<Duration>1 h 53 min</Duration>
<Duration>1 h 53 min 55 s 495 ms</Duration>
<Duration>1 h 53 min</Duration>
<Duration>01:53:55.495</Duration>
<Duration>01:53:55.495</Duration>
<Bit_rate>32630</Bit_rate>
<Bit_rate>32.6 kb/s</Bit_rate>
<Frame_rate>0.401</Frame_rate>
<Frame_rate>0.401 FPS</Frame_rate>
<Frame_count>2740</Frame_count>
<Count_of_elements>2740</Count_of_elements>
<Stream_size>27880889</Stream_size>
<Stream_size>26.6 MiB (0%)</Stream_size>
<Stream_size>27 MiB</Stream_size>
<Stream_size>27 MiB</Stream_size>
<Stream_size>26.6 MiB</Stream_size>
<Stream_size>26.59 MiB</Stream_size>
<Stream_size>26.6 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00055</Proportion_of_this_stream>
<Title>Dutch</Title>
<Language>nl</Language>
<Language>Dutch</Language>
<Language>Dutch</Language>
<Language>nl</Language>
<Language>dut</Language>
<Language>nl</Language>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Text" typeorder="6">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>5</Stream_identifier>
<Stream_identifier>6</Stream_identifier>
<StreamOrder>8</StreamOrder>
<ID>9</ID>
<ID>9</ID>
<Unique_ID>15698185840717251053</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>6835370.000000</Duration>
<Duration>1 h 53 min</Duration>
<Duration>1 h 53 min 55 s 370 ms</Duration>
<Duration>1 h 53 min</Duration>
<Duration>01:53:55.370</Duration>
<Duration>01:02:39</Duration>
<Duration>01:53:55.370 (01:02:39)</Duration>
<Bit_rate>44203</Bit_rate>
<Bit_rate>44.2 kb/s</Bit_rate>
<Frame_rate>0.550</Frame_rate>
<Frame_rate>0.550 FPS</Frame_rate>
<Frame_count>3758</Frame_count>
<Count_of_elements>3758</Count_of_elements>
<Stream_size>37768120</Stream_size>
<Stream_size>36.0 MiB (0%)</Stream_size>
<Stream_size>36 MiB</Stream_size>
<Stream_size>36 MiB</Stream_size>
<Stream_size>36.0 MiB</Stream_size>
<Stream_size>36.02 MiB</Stream_size>
<Stream_size>36.0 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00074</Proportion_of_this_stream>
<Title>Finnish</Title>
<Language>fi</Language>
<Language>Finnish</Language>
<Language>Finnish</Language>
<Language>fi</Language>
<Language>fin</Language>
<Language>fi</Language>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Text" typeorder="7">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>6</Stream_identifier>
<Stream_identifier>7</Stream_identifier>
<StreamOrder>9</StreamOrder>
<ID>10</ID>
<ID>10</ID>
<Unique_ID>13042625240473632450</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>6838915.000000</Duration>
<Duration>1 h 53 min</Duration>
<Duration>1 h 53 min 58 s 915 ms</Duration>
<Duration>1 h 53 min</Duration>
<Duration>01:53:58.915</Duration>
<Duration>01:03:16</Duration>
<Duration>01:53:58.915 (01:03:16)</Duration>
<Bit_rate>47204</Bit_rate>
<Bit_rate>47.2 kb/s</Bit_rate>
<Frame_rate>0.555</Frame_rate>
<Frame_rate>0.555 FPS</Frame_rate>
<Frame_count>3796</Frame_count>
<Count_of_elements>3796</Count_of_elements>
<Stream_size>40353814</Stream_size>
<Stream_size>38.5 MiB (0%)</Stream_size>
<Stream_size>38 MiB</Stream_size>
<Stream_size>38 MiB</Stream_size>
<Stream_size>38.5 MiB</Stream_size>
<Stream_size>38.48 MiB</Stream_size>
<Stream_size>38.5 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00079</Proportion_of_this_stream>
<Title>French (Canadian)</Title>
<Language>fr</Language>
<Language>French</Language>
<Language>French</Language>
<Language>fr</Language>
<Language>fra</Language>
<Language>fr</Language>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Text" typeorder="8">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>7</Stream_identifier>
<Stream_identifier>8</Stream_identifier>
<StreamOrder>10</StreamOrder>
<ID>11</ID>
<ID>11</ID>
<Unique_ID>9384674646401453741</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>6835370.000000</Duration>
<Duration>1 h 53 min</Duration>
<Duration>1 h 53 min 55 s 370 ms</Duration>
<Duration>1 h 53 min</Duration>
<Duration>01:53:55.370</Duration>
<Duration>01:53:55.370</Duration>
<Bit_rate>33756</Bit_rate>
<Bit_rate>33.8 kb/s</Bit_rate>
<Frame_rate>0.497</Frame_rate>
<Frame_rate>0.497 FPS</Frame_rate>
<Frame_count>3396</Frame_count>
<Count_of_elements>3396</Count_of_elements>
<Stream_size>28841848</Stream_size>
<Stream_size>27.5 MiB (0%)</Stream_size>
<Stream_size>28 MiB</Stream_size>
<Stream_size>28 MiB</Stream_size>
<Stream_size>27.5 MiB</Stream_size>
<Stream_size>27.51 MiB</Stream_size>
<Stream_size>27.5 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00057</Proportion_of_this_stream>
<Title>French (Parisian)</Title>
<Language>fr</Language>
<Language>French</Language>
<Language>French</Language>
<Language>fr</Language>
<Language>fra</Language>
<Language>fr</Language>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Text" typeorder="9">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>8</Stream_identifier>
<Stream_identifier>9</Stream_identifier>
<StreamOrder>11</StreamOrder>
<ID>12</ID>
<ID>12</ID>
<Unique_ID>11549195148942046264</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>6835370.000000</Duration>
<Duration>1 h 53 min</Duration>
<Duration>1 h 53 min 55 s 370 ms</Duration>
<Duration>1 h 53 min</Duration>
<Duration>01:53:55.370</Duration>
<Duration>01:01:38</Duration>
<Duration>01:53:55.370 (01:01:38)</Duration>
<Bit_rate>39016</Bit_rate>
<Bit_rate>39.0 kb/s</Bit_rate>
<Frame_rate>0.541</Frame_rate>
<Frame_rate>0.541 FPS</Frame_rate>
<Frame_count>3696</Frame_count>
<Count_of_elements>3696</Count_of_elements>
<Stream_size>33336937</Stream_size>
<Stream_size>31.8 MiB (0%)</Stream_size>
<Stream_size>32 MiB</Stream_size>
<Stream_size>32 MiB</Stream_size>
<Stream_size>31.8 MiB</Stream_size>
<Stream_size>31.79 MiB</Stream_size>
<Stream_size>31.8 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00065</Proportion_of_this_stream>
<Title>German</Title>
<Language>de</Language>
<Language>German</Language>
<Language>German</Language>
<Language>de</Language>
<Language>deu</Language>
<Language>de</Language>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Text" typeorder="10">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>9</Stream_identifier>
<Stream_identifier>10</Stream_identifier>
<StreamOrder>12</StreamOrder>
<ID>13</ID>
<ID>13</ID>
<Unique_ID>2803457007462858881</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>6838915.000000</Duration>
<Duration>1 h 53 min</Duration>
<Duration>1 h 53 min 58 s 915 ms</Duration>
<Duration>1 h 53 min</Duration>
<Duration>01:53:58.915</Duration>
<Duration>01:02:14</Duration>
<Duration>01:53:58.915 (01:02:14)</Duration>
<Bit_rate>37694</Bit_rate>
<Bit_rate>37.7 kb/s</Bit_rate>
<Frame_rate>0.546</Frame_rate>
<Frame_rate>0.546 FPS</Frame_rate>
<Frame_count>3732</Frame_count>
<Count_of_elements>3732</Count_of_elements>
<Stream_size>32223699</Stream_size>
<Stream_size>30.7 MiB (0%)</Stream_size>
<Stream_size>31 MiB</Stream_size>
<Stream_size>31 MiB</Stream_size>
<Stream_size>30.7 MiB</Stream_size>
<Stream_size>30.73 MiB</Stream_size>
<Stream_size>30.7 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00063</Proportion_of_this_stream>
<Title>Italian</Title>
<Language>it</Language>
<Language>Italian</Language>
<Language>Italian</Language>
<Language>it</Language>
<Language>ita</Language>
<Language>it</Language>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Text" typeorder="11">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>10</Stream_identifier>
<Stream_identifier>11</Stream_identifier>
<StreamOrder>13</StreamOrder>
<ID>14</ID>
<ID>14</ID>
<Unique_ID>14230295932882288116</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>6837706.000000</Duration>
<Duration>1 h 53 min</Duration>
<Duration>1 h 53 min 57 s 706 ms</Duration>
<Duration>1 h 53 min</Duration>
<Duration>01:53:57.706</Duration>
<Duration>01:00:03</Duration>
<Duration>01:53:57.706 (01:00:03)</Duration>
<Bit_rate>30627</Bit_rate>
<Bit_rate>30.6 kb/s</Bit_rate>
<Frame_rate>0.527</Frame_rate>
<Frame_rate>0.527 FPS</Frame_rate>
<Frame_count>3605</Frame_count>
<Count_of_elements>3605</Count_of_elements>
<Stream_size>26177603</Stream_size>
<Stream_size>25.0 MiB (0%)</Stream_size>
<Stream_size>25 MiB</Stream_size>
<Stream_size>25 MiB</Stream_size>
<Stream_size>25.0 MiB</Stream_size>
<Stream_size>24.96 MiB</Stream_size>
<Stream_size>25.0 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00051</Proportion_of_this_stream>
<Title>Japanese</Title>
<Language>ja</Language>
<Language>Japanese</Language>
<Language>Japanese</Language>
<Language>ja</Language>
<Language>jpn</Language>
<Language>ja</Language>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Text" typeorder="12">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>11</Stream_identifier>
<Stream_identifier>12</Stream_identifier>
<StreamOrder>14</StreamOrder>
<ID>15</ID>
<ID>15</ID>
<Unique_ID>10376337218316242587</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>6835370.000000</Duration>
<Duration>1 h 53 min</Duration>
<Duration>1 h 53 min 55 s 370 ms</Duration>
<Duration>1 h 53 min</Duration>
<Duration>01:53:55.370</Duration>
<Duration>01:03:00</Duration>
<Duration>01:53:55.370 (01:03:00)</Duration>
<Bit_rate>38616</Bit_rate>
<Bit_rate>38.6 kb/s</Bit_rate>
<Frame_rate>0.553</Frame_rate>
<Frame_rate>0.553 FPS</Frame_rate>
<Frame_count>3780</Frame_count>
<Count_of_elements>3780</Count_of_elements>
<Stream_size>32994492</Stream_size>
<Stream_size>31.5 MiB (0%)</Stream_size>
<Stream_size>31 MiB</Stream_size>
<Stream_size>31 MiB</Stream_size>
<Stream_size>31.5 MiB</Stream_size>
<Stream_size>31.47 MiB</Stream_size>
<Stream_size>31.5 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00065</Proportion_of_this_stream>
<Title>Norwegian</Title>
<Language>no</Language>
<Language>Norwegian</Language>
<Language>Norwegian</Language>
<Language>no</Language>
<Language>nor</Language>
<Language>no</Language>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Text" typeorder="13">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>12</Stream_identifier>
<Stream_identifier>13</Stream_identifier>
<StreamOrder>15</StreamOrder>
<ID>16</ID>
<ID>16</ID>
<Unique_ID>5657706296862527688</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>6835370.000000</Duration>
<Duration>1 h 53 min</Duration>
<Duration>1 h 53 min 55 s 370 ms</Duration>
<Duration>1 h 53 min</Duration>
<Duration>01:53:55.370</Duration>
<Duration>00:58:54</Duration>
<Duration>01:53:55.370 (00:58:54)</Duration>
<Bit_rate>35271</Bit_rate>
<Bit_rate>35.3 kb/s</Bit_rate>
<Frame_rate>0.517</Frame_rate>
<Frame_rate>0.517 FPS</Frame_rate>
<Frame_count>3532</Frame_count>
<Count_of_elements>3532</Count_of_elements>
<Stream_size>30136933</Stream_size>
<Stream_size>28.7 MiB (0%)</Stream_size>
<Stream_size>29 MiB</Stream_size>
<Stream_size>29 MiB</Stream_size>
<Stream_size>28.7 MiB</Stream_size>
<Stream_size>28.74 MiB</Stream_size>
<Stream_size>28.7 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00059</Proportion_of_this_stream>
<Title>Polish</Title>
<Language>pl</Language>
<Language>Polish</Language>
<Language>Polish</Language>
<Language>pl</Language>
<Language>pol</Language>
<Language>pl</Language>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Text" typeorder="14">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>13</Stream_identifier>
<Stream_identifier>14</Stream_identifier>
<StreamOrder>16</StreamOrder>
<ID>17</ID>
<ID>17</ID>
<Unique_ID>3117242445330710858</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>6837164.000000</Duration>
<Duration>1 h 53 min</Duration>
<Duration>1 h 53 min 57 s 164 ms</Duration>
<Duration>1 h 53 min</Duration>
<Duration>01:53:57.164</Duration>
<Duration>01:02:40</Duration>
<Duration>01:53:57.164 (01:02:40)</Duration>
<Bit_rate>38811</Bit_rate>
<Bit_rate>38.8 kb/s</Bit_rate>
<Frame_rate>0.550</Frame_rate>
<Frame_rate>0.550 FPS</Frame_rate>
<Frame_count>3758</Frame_count>
<Count_of_elements>3758</Count_of_elements>
<Stream_size>33169707</Stream_size>
<Stream_size>31.6 MiB (0%)</Stream_size>
<Stream_size>32 MiB</Stream_size>
<Stream_size>32 MiB</Stream_size>
<Stream_size>31.6 MiB</Stream_size>
<Stream_size>31.63 MiB</Stream_size>
<Stream_size>31.6 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00065</Proportion_of_this_stream>
<Title>Spanish (Castilian)</Title>
<Language>es</Language>
<Language>Spanish</Language>
<Language>Spanish</Language>
<Language>es</Language>
<Language>spa</Language>
<Language>es</Language>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Text" typeorder="15">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>14</Stream_identifier>
<Stream_identifier>15</Stream_identifier>
<StreamOrder>17</StreamOrder>
<ID>18</ID>
<ID>18</ID>
<Unique_ID>9327364905166507852</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>6325069.000000</Duration>
<Duration>1 h 45 min</Duration>
<Duration>1 h 45 min 25 s 69 ms</Duration>
<Duration>1 h 45 min</Duration>
<Duration>01:45:25.069</Duration>
<Duration>01:03:02</Duration>
<Duration>01:45:25.069 (01:03:02)</Duration>
<Bit_rate>50016</Bit_rate>
<Bit_rate>50.0 kb/s</Bit_rate>
<Frame_rate>0.598</Frame_rate>
<Frame_rate>0.598 FPS</Frame_rate>
<Frame_count>3780</Frame_count>
<Count_of_elements>3780</Count_of_elements>
<Stream_size>39544734</Stream_size>
<Stream_size>37.7 MiB (0%)</Stream_size>
<Stream_size>38 MiB</Stream_size>
<Stream_size>38 MiB</Stream_size>
<Stream_size>37.7 MiB</Stream_size>
<Stream_size>37.71 MiB</Stream_size>
<Stream_size>37.7 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00078</Proportion_of_this_stream>
<Title>Spanish (Latin American)</Title>
<Language>es</Language>
<Language>Spanish</Language>
<Language>Spanish</Language>
<Language>es</Language>
<Language>spa</Language>
<Language>es</Language>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Text" typeorder="16">
<Count>304</Count>
<Count_of_stream_of_this_kind>16</Count_of_stream_of_this_kind>
<Kind_of_stream>Text</Kind_of_stream>
<Kind_of_stream>Text</Kind_of_stream>
<Stream_identifier>15</Stream_identifier>
<Stream_identifier>16</Stream_identifier>
<StreamOrder>18</StreamOrder>
<ID>19</ID>
<ID>19</ID>
<Unique_ID>13516492667580207376</Unique_ID>
<Format>PGS</Format>
<Format>PGS</Format>
<Commercial_name>PGS</Commercial_name>
<Codec_ID>S_HDMV/PGS</Codec_ID>
<Codec_ID_Info>Picture based subtitle format used on BDs/HD-DVDs</Codec_ID_Info>
<Duration>6836872.000000</Duration>
<Duration>1 h 53 min</Duration>
<Duration>1 h 53 min 56 s 872 ms</Duration>
<Duration>1 h 53 min</Duration>
<Duration>01:53:56.872</Duration>
<Duration>01:53:56.872</Duration>
<Bit_rate>30843</Bit_rate>
<Bit_rate>30.8 kb/s</Bit_rate>
<Frame_rate>0.309</Frame_rate>
<Frame_rate>0.309 FPS</Frame_rate>
<Frame_count>2110</Frame_count>
<Count_of_elements>2110</Count_of_elements>
<Stream_size>26358990</Stream_size>
<Stream_size>25.1 MiB (0%)</Stream_size>
<Stream_size>25 MiB</Stream_size>
<Stream_size>25 MiB</Stream_size>
<Stream_size>25.1 MiB</Stream_size>
<Stream_size>25.14 MiB</Stream_size>
<Stream_size>25.1 MiB (0%)</Stream_size>
<Proportion_of_this_stream>0.00052</Proportion_of_this_stream>
<Title>Swedish</Title>
<Language>sv</Language>
<Language>Swedish</Language>
<Language>Swedish</Language>
<Language>sv</Language>
<Language>swe</Language>
<Language>sv</Language>
<Default>No</Default>
<Default>No</Default>
<Forced>No</Forced>
<Forced>No</Forced>
</track>
<track type="Menu">
<Count>125</Count>
<Count_of_stream_of_this_kind>1</Count_of_stream_of_this_kind>
<Kind_of_stream>Menu</Kind_of_stream>
<Kind_of_stream>Menu</Kind_of_stream>
<Stream_identifier>0</Stream_identifier>
<Chapters_Pos_Begin>101</Chapters_Pos_Begin>
<Chapters_Pos_End>125</Chapters_Pos_End>
<_00_00_00000>en:Chapter 1</_00_00_00000>
<_00_05_09100>en:Chapter 2</_00_05_09100>
<_00_08_43815>en:Chapter 3</_00_08_43815>
<_00_14_29702>en:Chapter 4</_00_14_29702>
<_00_21_25701>en:Chapter 5</_00_21_25701>
<_00_24_06028>en:Chapter 6</_00_24_06028>
<_00_28_25245>en:Chapter 7</_00_28_25245>
<_00_34_21810>en:Chapter 8</_00_34_21810>
<_00_39_40837>en:Chapter 9</_00_39_40837>
<_00_44_10731>en:Chapter 10</_00_44_10731>
<_00_48_47967>en:Chapter 11</_00_48_47967>
<_00_52_47748>en:Chapter 12</_00_52_47748>
<_00_56_18375>en:Chapter 13</_00_56_18375>
<_01_00_17739>en:Chapter 14</_01_00_17739>
<_01_04_41920>en:Chapter 15</_01_04_41920>
<_01_09_13816>en:Chapter 16</_01_09_13816>
<_01_15_13300>en:Chapter 17</_01_15_13300>
<_01_19_14083>en:Chapter 18</_01_19_14083>
<_01_23_59326>en:Chapter 19</_01_23_59326>
<_01_28_06406>en:Chapter 20</_01_28_06406>
<_01_33_07415>en:Chapter 21</_01_33_07415>
<_01_39_19954>en:Chapter 22</_01_39_19954>
<_01_44_22506>en:Chapter 23</_01_44_22506>
<_01_46_13993>en:Chapter 24</_01_46_13993>
</track>
</File>
</Mediainfo>"""

EXAMPLE_MEDIAINFO_OBJ = MediaInfo(_EXAMPLE_MEDIAINFO_XML_DATA)


EXAMPLE_MEDIAINFO_OUTPUT_STR = f"""\
General
-------
Count                                             : 351
Count_of_stream_of_this_kind                      : 1
Kind_of_stream                                    : General
Kind_of_stream                                    : General
Stream_identifier                                 : 0
Unique_ID                                         : 72016458352865119504084926981396730566
Unique_ID                                         : 72016458352865119504084926981396730566 (0x362DDD886EE76435518FF5DA845A32C0)
Count_of_video_streams                            : 1
Count_of_audio_streams                            : 2
Count_of_text_streams                             : 16
Count_of_menu_streams                             : 1
Video_Format_List                                 : HEVC
Video_Format_WithHint_List                        : HEVC
Codecs_Video                                      : HEVC
Audio_Format_List                                 : MLP FBA 16-ch / AC-3
Audio_Format_WithHint_List                        : MLP FBA 16-ch / AC-3
Audio_codecs                                      : MLP FBA 16-ch / AC-3
Audio_Language_List                               : English / English
Audio_Channels_Total                              : 14
Text_Format_List                                  : PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS
Text_Format_WithHint_List                         : PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS
Text_codecs                                       : PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS / PGS
Text_Language_List                                : English / English / Czech / Danish / Dutch / Finnish / French / French / German / Italian / Japanese / Norwegian / Polish / Spanish / Spanish / Swedish
Complete_name                                     : /some_path/Movie.Name.{current_year}.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.HYBRID.REMUX-SomeGroup/Movie.Name.{current_year}.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.HYBRID.REMUX-SomeGroup.mkv
Folder_name                                       : /some_path/Movie.Name.{current_year}.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.HYBRID.REMUX-SomeGroup
File_name_extension                               : Movie.Name.{current_year}.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.HYBRID.REMUX-SomeGroup.mkv
File_name                                         : Movie.Name.{current_year}.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.HYBRID.REMUX-SomeGroup
File_extension                                    : mkv
Format                                            : Matroska
Format                                            : Matroska
Format_Url                                        : https://matroska.org/downloads/windows.html
Format_Extensions_usually_used                    : mkv mk3d mka mks
Commercial_name                                   : Matroska
Format_version                                    : Version 4
File_size                                         : 51013759049
File_size                                         : 47.5 GiB
File_size                                         : 48 GiB
File_size                                         : 48 GiB
File_size                                         : 47.5 GiB
File_size                                         : 47.51 GiB
Duration                                          : 6898624
Duration                                          : 1 h 54 min
Duration                                          : 1 h 54 min 58 s 624 ms
Duration                                          : 1 h 54 min
Duration                                          : 01:54:58.624
Duration                                          : 01:55:00;09
Duration                                          : 01:54:58.624 (01:55:00;09)
Overall_bit_rate_mode                             : VBR
Overall_bit_rate_mode                             : Variable
Overall_bit_rate                                  : 59158185
Overall_bit_rate                                  : 59.2 Mb/s
Frame_rate                                        : 23.976
Frame_rate                                        : 23.976 FPS
Frame_count                                       : 165401
Stream_size                                       : 61820330
Stream_size                                       : 59.0 MiB (0%)
Stream_size                                       : 59 MiB
Stream_size                                       : 59 MiB
Stream_size                                       : 59.0 MiB
Stream_size                                       : 58.96 MiB
Stream_size                                       : 59.0 MiB (0%)
Proportion_of_this_stream                         : 0.00121
IsStreamable                                      : Yes
Title                                             : Movie Name ({current_year})
Movie_name                                        : Movie Name ({current_year})
Encoded_date                                      : 2022-08-30 09:36:09 UTC
File_creation_date                                : 2025-02-15 04:27:46.480 UTC
File_creation_date__local_                        : 2025-02-14 23:27:46.480
File_last_modification_date                       : 2025-02-15 04:59:16.866 UTC
File_last_modification_date__local_               : 2025-02-14 23:59:16.866
Writing_application                               : mkvmerge v70.0.0 ('Caught A Lite Sneeze') 64-bit
Writing_application                               : mkvmerge v70.0.0 ('Caught A Lite Sneeze') 64-bit
Writing_library                                   : libebml v1.4.2 + libmatroska v1.6.4
Writing_library                                   : libebml v1.4.2 + libmatroska v1.6.4
IMDB                                              : tt6264654
TMDB                                              : movie/550988

Video
-----
Count                                             : 381
Count_of_stream_of_this_kind                      : 1
Kind_of_stream                                    : Video
Kind_of_stream                                    : Video
Stream_identifier                                 : 0
StreamOrder                                       : 0
ID                                                : 1
ID                                                : 1
Unique_ID                                         : 12437146302198571983
Format                                            : HEVC
Format                                            : HEVC
Format_Info                                       : High Efficiency Video Coding
Format_Url                                        : http://www.itu.int
Commercial_name                                   : HEVC
Format_profile                                    : Main 10@L5.1@High
HDR_format                                        : Dolby Vision / SMPTE ST 2086
HDR_format                                        : Dolby Vision, Version 1.0, dvhe.08.06, BL+RPU, HDR10 compatible / SMPTE ST 2086, HDR10 compatible
HDR_Format_Commercial                             : HDR10 / HDR10
HDR_Format_Version                                : 1.0 / 
HDR_Format_Profile                                : dvhe.08 / 
HDR_Format_Level                                  : 06 / 
HDR_Format_Settings                               : BL+RPU / 
HDR_Format_Compatibility                          : HDR10 / HDR10
Internet_media_type                               : video/H265
Codec_ID                                          : V_MPEGH/ISO/HEVC
Duration                                          : 6898600.000000
Duration                                          : 1 h 54 min
Duration                                          : 1 h 54 min 58 s 600 ms
Duration                                          : 1 h 54 min
Duration                                          : 01:54:58.600
Duration                                          : 01:55:00;09
Duration                                          : 01:54:58.600 (01:55:00;09)
Bit_rate                                          : 49960501
Bit_rate                                          : 50.0 Mb/s
Width                                             : 3840
Width                                             : 3 840 pixels
Height                                            : 2160
Height                                            : 2 160 pixels
Sampled_Width                                     : 3840
Sampled_Height                                    : 2160
Pixel_aspect_ratio                                : 1.000
Display_aspect_ratio                              : 1.778
Display_aspect_ratio                              : 16:9
Frame_rate_mode                                   : CFR
Frame_rate_mode                                   : Constant
Frame_rate                                        : 23.976
Frame_rate                                        : 23.976 (24000/1001) FPS
FrameRate_Num                                     : 24000
FrameRate_Den                                     : 1001
Frame_count                                       : 165401
Color_space                                       : YUV
Chroma_subsampling                                : 4:2:0
Chroma_subsampling                                : 4:2:0 (Type 2)
ChromaSubsampling_Position                        : Type 2
Bit_depth                                         : 10
Bit_depth                                         : 10 bits
Bits__Pixel_Frame_                                : 0.251
Delay                                             : 0
Delay                                             : 00:00:00.000
Delay                                             : 00:00:00;00
Delay                                             : 00:00:00.000 (00:00:00;00)
Delay__origin                                     : Container
Delay__origin                                     : Container
Stream_size                                       : 43082189302
Stream_size                                       : 40.1 GiB (84%)
Stream_size                                       : 40 GiB
Stream_size                                       : 40 GiB
Stream_size                                       : 40.1 GiB
Stream_size                                       : 40.12 GiB
Stream_size                                       : 40.1 GiB (84%)
Proportion_of_this_stream                         : 0.84452
Writing_library                                   : ATEME Titan File 3.9.6 (4.9.6.2)        
Writing_library                                   : ATEME Titan File 3.9.6 (4.9.6.2)        
Encoded_Library_Name                              : ATEME Titan File
Encoded_Library_Version                           : 3.9.6 (4.9.6.2)        
Default                                           : Yes
Default                                           : Yes
Forced                                            : No
Forced                                            : No
colour_description_present                        : Yes
colour_description_present_Source                 : Stream
Color_range                                       : Limited
colour_range_Source                               : Stream
Color_primaries                                   : BT.2020
colour_primaries_Source                           : Stream
Transfer_characteristics                          : PQ
transfer_characteristics_Source                   : Stream
Matrix_coefficients                               : BT.2020 non-constant
matrix_coefficients_Source                        : Stream
Mastering_display_color_primaries                 : Display P3
MasteringDisplay_ColorPrimaries_Source            : Stream
Mastering_display_luminance                       : min: 0.0050 cd/m2, max: 1000 cd/m2
MasteringDisplay_Luminance_Source                 : Stream

Audio
-----
Count                                             : 289
Count_of_stream_of_this_kind                      : 2
Kind_of_stream                                    : Audio
Kind_of_stream                                    : Audio
Stream_identifier                                 : 0
Stream_identifier                                 : 1
StreamOrder                                       : 1
ID                                                : 2
ID                                                : 2
Unique_ID                                         : 2164772528079252818
Format                                            : MLP FBA
Format                                            : MLP FBA 16-ch
Format_Info                                       : Meridian Lossless Packing FBA with 16-channel presentation
Commercial_name                                   : Dolby TrueHD with Dolby Atmos
Commercial_name                                   : Dolby TrueHD with Dolby Atmos
Format_AdditionalFeatures                         : 16-ch
Codec_ID                                          : A_TRUEHD
Codec_ID_Url                                      : http://www.dolby.com/consumer/technology/trueHD.html
Duration                                          : 6898600.000000
Duration                                          : 1 h 54 min
Duration                                          : 1 h 54 min 58 s 600 ms
Duration                                          : 1 h 54 min
Duration                                          : 01:54:58.600
Duration                                          : 01:54:58.600
Bit_rate_mode                                     : VBR
Bit_rate_mode                                     : Variable
Bit_rate                                          : 7912031
Bit_rate                                          : 7 912 kb/s
Maximum_bit_rate                                  : 12942000
Maximum_bit_rate                                  : 12.9 Mb/s
Channel_s_                                        : 8
Channel_s_                                        : 8 channels
Channel_positions                                 : Front: L C R, Side: L R, Back: L R, LFE
Channel_positions                                 : 3/2/2.1
Channel_layout                                    : L R C LFE Ls Rs Lb Rb
Samples_per_frame                                 : 40
Sampling_rate                                     : 48000
Sampling_rate                                     : 48.0 kHz
Samples_count                                     : 331132800
Frame_rate                                        : 1200.000
Frame_rate                                        : 1 200.000 FPS (40 SPF)
FrameRate_Num                                     : 1200
FrameRate_Den                                     : 1
Frame_count                                       : 8278320
Compression_mode                                  : Lossless
Compression_mode                                  : Lossless
Delay                                             : 0
Delay                                             : 00:00:00.000
Delay                                             : 00:00:00.000
Delay__origin                                     : Container
Delay__origin                                     : Container
Delay_relative_to_video                           : 0
Delay_relative_to_video                           : 00:00:00.000
Delay_relative_to_video                           : 00:00:00.000
Stream_size                                       : 6822742600
Stream_size                                       : 6.35 GiB (13%)
Stream_size                                       : 6 GiB
Stream_size                                       : 6.4 GiB
Stream_size                                       : 6.35 GiB
Stream_size                                       : 6.354 GiB
Stream_size                                       : 6.35 GiB (13%)
Proportion_of_this_stream                         : 0.13374
Title                                             : TrueHD Atmos 7.1
Language                                          : en
Language                                          : English
Language                                          : English
Language                                          : en
Language                                          : eng
Language                                          : en
Default                                           : Yes
Default                                           : Yes
Forced                                            : No
Forced                                            : No
Number_of_dynamic_objects                         : 13
Bed_channel_count                                 : 1
Bed_channel_count                                 : 1 channel
Bed_channel_configuration                         : LFE

Audio
-----
Count                                             : 313
Count_of_stream_of_this_kind                      : 2
Kind_of_stream                                    : Audio
Kind_of_stream                                    : Audio
Stream_identifier                                 : 1
Stream_identifier                                 : 2
StreamOrder                                       : 2
ID                                                : 3
ID                                                : 3
Unique_ID                                         : 7017140953773492237
Format                                            : AC-3
Format                                            : AC-3
Format_Info                                       : Audio Coding 3
Format_Url                                        : https://en.wikipedia.org/wiki/AC3
Commercial_name                                   : Dolby Digital
Commercial_name                                   : Dolby Digital
Format_settings__Endianness                       : Big
Codec_ID                                          : A_AC3
Duration                                          : 6898624.000000
Duration                                          : 1 h 54 min
Duration                                          : 1 h 54 min 58 s 624 ms
Duration                                          : 1 h 54 min
Duration                                          : 01:54:58.624
Duration                                          : 01:54:58.624
Bit_rate_mode                                     : CBR
Bit_rate_mode                                     : Constant
Bit_rate                                          : 640000
Bit_rate                                          : 640 kb/s
Channel_s_                                        : 6
Channel_s_                                        : 6 channels
Channel_positions                                 : Front: L C R, Side: L R, LFE
Channel_positions                                 : 3/2/0.1
Channel_layout                                    : L R C LFE Ls Rs
Samples_per_frame                                 : 1536
Sampling_rate                                     : 48000
Sampling_rate                                     : 48.0 kHz
Samples_count                                     : 331133952
Frame_rate                                        : 31.250
Frame_rate                                        : 31.250 FPS (1536 SPF)
Frame_count                                       : 215582
Compression_mode                                  : Lossy
Compression_mode                                  : Lossy
Delay                                             : 0
Delay                                             : 00:00:00.000
Delay                                             : 00:00:00.000
Delay__origin                                     : Container
Delay__origin                                     : Container
Delay_relative_to_video                           : 0
Delay_relative_to_video                           : 00:00:00.000
Delay_relative_to_video                           : 00:00:00.000
Stream_size                                       : 551889920
Stream_size                                       : 526 MiB (1%)
Stream_size                                       : 526 MiB
Stream_size                                       : 526 MiB
Stream_size                                       : 526 MiB
Stream_size                                       : 526.3 MiB
Stream_size                                       : 526 MiB (1%)
Proportion_of_this_stream                         : 0.01082
Title                                             : AC-3 5.1
Language                                          : en
Language                                          : English
Language                                          : English
Language                                          : en
Language                                          : eng
Language                                          : en
Service_kind                                      : CM
Service_kind                                      : Complete Main
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No
bsid                                              : 6
Dialog_Normalization                              : -31
Dialog_Normalization                              : -31 dB
compr                                             : -0.28
compr                                             : -0.28 dB
acmod                                             : 7
lfeon                                             : 1
dialnorm_Average                                  : -31
dialnorm_Average                                  : -31 dB
dialnorm_Minimum                                  : -31
dialnorm_Minimum                                  : -31 dB
dialnorm_Maximum                                  : -31
dialnorm_Maximum                                  : -31 dB
dialnorm_Count                                    : 247
compr_Average                                     : 1.77
compr_Average                                     : 1.77 dB
compr_Minimum                                     : 0.53
compr_Minimum                                     : 0.53 dB
compr_Maximum                                     : 3.15
compr_Maximum                                     : 3.15 dB
compr_Count                                       : 77
dynrng_Average                                    : 0.47
dynrng_Average                                    : 0.47 dB
dynrng_Minimum                                    : 0.00
dynrng_Minimum                                    : 0.00 dB
dynrng_Maximum                                    : 2.57
dynrng_Maximum                                    : 2.57 dB
dynrng_Count                                      : 247

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 0
Stream_identifier                                 : 1
StreamOrder                                       : 3
ID                                                : 4
ID                                                : 4
Unique_ID                                         : 15030197436603000446
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 13597.000000
Duration                                          : 13 s 597 ms
Duration                                          : 13 s 597 ms
Duration                                          : 13 s 597 ms
Duration                                          : 00:00:13.597
Duration                                          : 00:00:12
Duration                                          : 00:00:13.597 (00:00:12)
Bit_rate                                          : 64220
Bit_rate                                          : 64.2 kb/s
Frame_rate                                        : 0.883
Frame_rate                                        : 0.883 FPS
Frame_count                                       : 12
Count_of_elements                                 : 12
Stream_size                                       : 109150
Stream_size                                       : 107 KiB (0%)
Stream_size                                       : 107 KiB
Stream_size                                       : 107 KiB
Stream_size                                       : 107 KiB
Stream_size                                       : 106.6 KiB
Stream_size                                       : 107 KiB (0%)
Proportion_of_this_stream                         : 0.00000
Title                                             : English (Forced)
Language                                          : en
Language                                          : English
Language                                          : English
Language                                          : en
Language                                          : eng
Language                                          : en
Default                                           : Yes
Default                                           : Yes
Forced                                            : Yes
Forced                                            : Yes

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 1
Stream_identifier                                 : 2
StreamOrder                                       : 4
ID                                                : 5
ID                                                : 5
Unique_ID                                         : 850369776613837289
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 6333578.000000
Duration                                          : 1 h 45 min
Duration                                          : 1 h 45 min 33 s 578 ms
Duration                                          : 1 h 45 min
Duration                                          : 01:45:33.578
Duration                                          : 01:11:09
Duration                                          : 01:45:33.578 (01:11:09)
Bit_rate                                          : 57706
Bit_rate                                          : 57.7 kb/s
Frame_rate                                        : 0.674
Frame_rate                                        : 0.674 FPS
Frame_count                                       : 4270
Count_of_elements                                 : 4270
Stream_size                                       : 45686339
Stream_size                                       : 43.6 MiB (0%)
Stream_size                                       : 44 MiB
Stream_size                                       : 44 MiB
Stream_size                                       : 43.6 MiB
Stream_size                                       : 43.57 MiB
Stream_size                                       : 43.6 MiB (0%)
Proportion_of_this_stream                         : 0.00090
Title                                             : English (SDH)
Language                                          : en
Language                                          : English
Language                                          : English
Language                                          : en
Language                                          : eng
Language                                          : en
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 2
Stream_identifier                                 : 3
StreamOrder                                       : 5
ID                                                : 6
ID                                                : 6
Unique_ID                                         : 17430780143545358465
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 6835370.000000
Duration                                          : 1 h 53 min
Duration                                          : 1 h 53 min 55 s 370 ms
Duration                                          : 1 h 53 min
Duration                                          : 01:53:55.370
Duration                                          : 01:02:39
Duration                                          : 01:53:55.370 (01:02:39)
Bit_rate                                          : 36792
Bit_rate                                          : 36.8 kb/s
Frame_rate                                        : 0.550
Frame_rate                                        : 0.550 FPS
Frame_count                                       : 3758
Count_of_elements                                 : 3758
Stream_size                                       : 31436688
Stream_size                                       : 30.0 MiB (0%)
Stream_size                                       : 30 MiB
Stream_size                                       : 30 MiB
Stream_size                                       : 30.0 MiB
Stream_size                                       : 29.98 MiB
Stream_size                                       : 30.0 MiB (0%)
Proportion_of_this_stream                         : 0.00062
Title                                             : Czech
Language                                          : cs
Language                                          : Czech
Language                                          : Czech
Language                                          : cs
Language                                          : ces
Language                                          : cs
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 3
Stream_identifier                                 : 4
StreamOrder                                       : 6
ID                                                : 7
ID                                                : 7
Unique_ID                                         : 4530733467076602432
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 6835370.000000
Duration                                          : 1 h 53 min
Duration                                          : 1 h 53 min 55 s 370 ms
Duration                                          : 1 h 53 min
Duration                                          : 01:53:55.370
Duration                                          : 01:53:55.370
Bit_rate                                          : 34054
Bit_rate                                          : 34.1 kb/s
Frame_rate                                        : 0.336
Frame_rate                                        : 0.336 FPS
Frame_count                                       : 2300
Count_of_elements                                 : 2300
Stream_size                                       : 29096954
Stream_size                                       : 27.7 MiB (0%)
Stream_size                                       : 28 MiB
Stream_size                                       : 28 MiB
Stream_size                                       : 27.7 MiB
Stream_size                                       : 27.75 MiB
Stream_size                                       : 27.7 MiB (0%)
Proportion_of_this_stream                         : 0.00057
Title                                             : Danish
Language                                          : da
Language                                          : Danish
Language                                          : Danish
Language                                          : da
Language                                          : dan
Language                                          : da
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 4
Stream_identifier                                 : 5
StreamOrder                                       : 7
ID                                                : 8
ID                                                : 8
Unique_ID                                         : 13393963019490599196
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 6835495.000000
Duration                                          : 1 h 53 min
Duration                                          : 1 h 53 min 55 s 495 ms
Duration                                          : 1 h 53 min
Duration                                          : 01:53:55.495
Duration                                          : 01:53:55.495
Bit_rate                                          : 32630
Bit_rate                                          : 32.6 kb/s
Frame_rate                                        : 0.401
Frame_rate                                        : 0.401 FPS
Frame_count                                       : 2740
Count_of_elements                                 : 2740
Stream_size                                       : 27880889
Stream_size                                       : 26.6 MiB (0%)
Stream_size                                       : 27 MiB
Stream_size                                       : 27 MiB
Stream_size                                       : 26.6 MiB
Stream_size                                       : 26.59 MiB
Stream_size                                       : 26.6 MiB (0%)
Proportion_of_this_stream                         : 0.00055
Title                                             : Dutch
Language                                          : nl
Language                                          : Dutch
Language                                          : Dutch
Language                                          : nl
Language                                          : dut
Language                                          : nl
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 5
Stream_identifier                                 : 6
StreamOrder                                       : 8
ID                                                : 9
ID                                                : 9
Unique_ID                                         : 15698185840717251053
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 6835370.000000
Duration                                          : 1 h 53 min
Duration                                          : 1 h 53 min 55 s 370 ms
Duration                                          : 1 h 53 min
Duration                                          : 01:53:55.370
Duration                                          : 01:02:39
Duration                                          : 01:53:55.370 (01:02:39)
Bit_rate                                          : 44203
Bit_rate                                          : 44.2 kb/s
Frame_rate                                        : 0.550
Frame_rate                                        : 0.550 FPS
Frame_count                                       : 3758
Count_of_elements                                 : 3758
Stream_size                                       : 37768120
Stream_size                                       : 36.0 MiB (0%)
Stream_size                                       : 36 MiB
Stream_size                                       : 36 MiB
Stream_size                                       : 36.0 MiB
Stream_size                                       : 36.02 MiB
Stream_size                                       : 36.0 MiB (0%)
Proportion_of_this_stream                         : 0.00074
Title                                             : Finnish
Language                                          : fi
Language                                          : Finnish
Language                                          : Finnish
Language                                          : fi
Language                                          : fin
Language                                          : fi
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 6
Stream_identifier                                 : 7
StreamOrder                                       : 9
ID                                                : 10
ID                                                : 10
Unique_ID                                         : 13042625240473632450
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 6838915.000000
Duration                                          : 1 h 53 min
Duration                                          : 1 h 53 min 58 s 915 ms
Duration                                          : 1 h 53 min
Duration                                          : 01:53:58.915
Duration                                          : 01:03:16
Duration                                          : 01:53:58.915 (01:03:16)
Bit_rate                                          : 47204
Bit_rate                                          : 47.2 kb/s
Frame_rate                                        : 0.555
Frame_rate                                        : 0.555 FPS
Frame_count                                       : 3796
Count_of_elements                                 : 3796
Stream_size                                       : 40353814
Stream_size                                       : 38.5 MiB (0%)
Stream_size                                       : 38 MiB
Stream_size                                       : 38 MiB
Stream_size                                       : 38.5 MiB
Stream_size                                       : 38.48 MiB
Stream_size                                       : 38.5 MiB (0%)
Proportion_of_this_stream                         : 0.00079
Title                                             : French (Canadian)
Language                                          : fr
Language                                          : French
Language                                          : French
Language                                          : fr
Language                                          : fra
Language                                          : fr
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 7
Stream_identifier                                 : 8
StreamOrder                                       : 10
ID                                                : 11
ID                                                : 11
Unique_ID                                         : 9384674646401453741
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 6835370.000000
Duration                                          : 1 h 53 min
Duration                                          : 1 h 53 min 55 s 370 ms
Duration                                          : 1 h 53 min
Duration                                          : 01:53:55.370
Duration                                          : 01:53:55.370
Bit_rate                                          : 33756
Bit_rate                                          : 33.8 kb/s
Frame_rate                                        : 0.497
Frame_rate                                        : 0.497 FPS
Frame_count                                       : 3396
Count_of_elements                                 : 3396
Stream_size                                       : 28841848
Stream_size                                       : 27.5 MiB (0%)
Stream_size                                       : 28 MiB
Stream_size                                       : 28 MiB
Stream_size                                       : 27.5 MiB
Stream_size                                       : 27.51 MiB
Stream_size                                       : 27.5 MiB (0%)
Proportion_of_this_stream                         : 0.00057
Title                                             : French (Parisian)
Language                                          : fr
Language                                          : French
Language                                          : French
Language                                          : fr
Language                                          : fra
Language                                          : fr
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 8
Stream_identifier                                 : 9
StreamOrder                                       : 11
ID                                                : 12
ID                                                : 12
Unique_ID                                         : 11549195148942046264
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 6835370.000000
Duration                                          : 1 h 53 min
Duration                                          : 1 h 53 min 55 s 370 ms
Duration                                          : 1 h 53 min
Duration                                          : 01:53:55.370
Duration                                          : 01:01:38
Duration                                          : 01:53:55.370 (01:01:38)
Bit_rate                                          : 39016
Bit_rate                                          : 39.0 kb/s
Frame_rate                                        : 0.541
Frame_rate                                        : 0.541 FPS
Frame_count                                       : 3696
Count_of_elements                                 : 3696
Stream_size                                       : 33336937
Stream_size                                       : 31.8 MiB (0%)
Stream_size                                       : 32 MiB
Stream_size                                       : 32 MiB
Stream_size                                       : 31.8 MiB
Stream_size                                       : 31.79 MiB
Stream_size                                       : 31.8 MiB (0%)
Proportion_of_this_stream                         : 0.00065
Title                                             : German
Language                                          : de
Language                                          : German
Language                                          : German
Language                                          : de
Language                                          : deu
Language                                          : de
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 9
Stream_identifier                                 : 10
StreamOrder                                       : 12
ID                                                : 13
ID                                                : 13
Unique_ID                                         : 2803457007462858881
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 6838915.000000
Duration                                          : 1 h 53 min
Duration                                          : 1 h 53 min 58 s 915 ms
Duration                                          : 1 h 53 min
Duration                                          : 01:53:58.915
Duration                                          : 01:02:14
Duration                                          : 01:53:58.915 (01:02:14)
Bit_rate                                          : 37694
Bit_rate                                          : 37.7 kb/s
Frame_rate                                        : 0.546
Frame_rate                                        : 0.546 FPS
Frame_count                                       : 3732
Count_of_elements                                 : 3732
Stream_size                                       : 32223699
Stream_size                                       : 30.7 MiB (0%)
Stream_size                                       : 31 MiB
Stream_size                                       : 31 MiB
Stream_size                                       : 30.7 MiB
Stream_size                                       : 30.73 MiB
Stream_size                                       : 30.7 MiB (0%)
Proportion_of_this_stream                         : 0.00063
Title                                             : Italian
Language                                          : it
Language                                          : Italian
Language                                          : Italian
Language                                          : it
Language                                          : ita
Language                                          : it
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 10
Stream_identifier                                 : 11
StreamOrder                                       : 13
ID                                                : 14
ID                                                : 14
Unique_ID                                         : 14230295932882288116
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 6837706.000000
Duration                                          : 1 h 53 min
Duration                                          : 1 h 53 min 57 s 706 ms
Duration                                          : 1 h 53 min
Duration                                          : 01:53:57.706
Duration                                          : 01:00:03
Duration                                          : 01:53:57.706 (01:00:03)
Bit_rate                                          : 30627
Bit_rate                                          : 30.6 kb/s
Frame_rate                                        : 0.527
Frame_rate                                        : 0.527 FPS
Frame_count                                       : 3605
Count_of_elements                                 : 3605
Stream_size                                       : 26177603
Stream_size                                       : 25.0 MiB (0%)
Stream_size                                       : 25 MiB
Stream_size                                       : 25 MiB
Stream_size                                       : 25.0 MiB
Stream_size                                       : 24.96 MiB
Stream_size                                       : 25.0 MiB (0%)
Proportion_of_this_stream                         : 0.00051
Title                                             : Japanese
Language                                          : ja
Language                                          : Japanese
Language                                          : Japanese
Language                                          : ja
Language                                          : jpn
Language                                          : ja
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 11
Stream_identifier                                 : 12
StreamOrder                                       : 14
ID                                                : 15
ID                                                : 15
Unique_ID                                         : 10376337218316242587
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 6835370.000000
Duration                                          : 1 h 53 min
Duration                                          : 1 h 53 min 55 s 370 ms
Duration                                          : 1 h 53 min
Duration                                          : 01:53:55.370
Duration                                          : 01:03:00
Duration                                          : 01:53:55.370 (01:03:00)
Bit_rate                                          : 38616
Bit_rate                                          : 38.6 kb/s
Frame_rate                                        : 0.553
Frame_rate                                        : 0.553 FPS
Frame_count                                       : 3780
Count_of_elements                                 : 3780
Stream_size                                       : 32994492
Stream_size                                       : 31.5 MiB (0%)
Stream_size                                       : 31 MiB
Stream_size                                       : 31 MiB
Stream_size                                       : 31.5 MiB
Stream_size                                       : 31.47 MiB
Stream_size                                       : 31.5 MiB (0%)
Proportion_of_this_stream                         : 0.00065
Title                                             : Norwegian
Language                                          : no
Language                                          : Norwegian
Language                                          : Norwegian
Language                                          : no
Language                                          : nor
Language                                          : no
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 12
Stream_identifier                                 : 13
StreamOrder                                       : 15
ID                                                : 16
ID                                                : 16
Unique_ID                                         : 5657706296862527688
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 6835370.000000
Duration                                          : 1 h 53 min
Duration                                          : 1 h 53 min 55 s 370 ms
Duration                                          : 1 h 53 min
Duration                                          : 01:53:55.370
Duration                                          : 00:58:54
Duration                                          : 01:53:55.370 (00:58:54)
Bit_rate                                          : 35271
Bit_rate                                          : 35.3 kb/s
Frame_rate                                        : 0.517
Frame_rate                                        : 0.517 FPS
Frame_count                                       : 3532
Count_of_elements                                 : 3532
Stream_size                                       : 30136933
Stream_size                                       : 28.7 MiB (0%)
Stream_size                                       : 29 MiB
Stream_size                                       : 29 MiB
Stream_size                                       : 28.7 MiB
Stream_size                                       : 28.74 MiB
Stream_size                                       : 28.7 MiB (0%)
Proportion_of_this_stream                         : 0.00059
Title                                             : Polish
Language                                          : pl
Language                                          : Polish
Language                                          : Polish
Language                                          : pl
Language                                          : pol
Language                                          : pl
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 13
Stream_identifier                                 : 14
StreamOrder                                       : 16
ID                                                : 17
ID                                                : 17
Unique_ID                                         : 3117242445330710858
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 6837164.000000
Duration                                          : 1 h 53 min
Duration                                          : 1 h 53 min 57 s 164 ms
Duration                                          : 1 h 53 min
Duration                                          : 01:53:57.164
Duration                                          : 01:02:40
Duration                                          : 01:53:57.164 (01:02:40)
Bit_rate                                          : 38811
Bit_rate                                          : 38.8 kb/s
Frame_rate                                        : 0.550
Frame_rate                                        : 0.550 FPS
Frame_count                                       : 3758
Count_of_elements                                 : 3758
Stream_size                                       : 33169707
Stream_size                                       : 31.6 MiB (0%)
Stream_size                                       : 32 MiB
Stream_size                                       : 32 MiB
Stream_size                                       : 31.6 MiB
Stream_size                                       : 31.63 MiB
Stream_size                                       : 31.6 MiB (0%)
Proportion_of_this_stream                         : 0.00065
Title                                             : Spanish (Castilian)
Language                                          : es
Language                                          : Spanish
Language                                          : Spanish
Language                                          : es
Language                                          : spa
Language                                          : es
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 14
Stream_identifier                                 : 15
StreamOrder                                       : 17
ID                                                : 18
ID                                                : 18
Unique_ID                                         : 9327364905166507852
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 6325069.000000
Duration                                          : 1 h 45 min
Duration                                          : 1 h 45 min 25 s 69 ms
Duration                                          : 1 h 45 min
Duration                                          : 01:45:25.069
Duration                                          : 01:03:02
Duration                                          : 01:45:25.069 (01:03:02)
Bit_rate                                          : 50016
Bit_rate                                          : 50.0 kb/s
Frame_rate                                        : 0.598
Frame_rate                                        : 0.598 FPS
Frame_count                                       : 3780
Count_of_elements                                 : 3780
Stream_size                                       : 39544734
Stream_size                                       : 37.7 MiB (0%)
Stream_size                                       : 38 MiB
Stream_size                                       : 38 MiB
Stream_size                                       : 37.7 MiB
Stream_size                                       : 37.71 MiB
Stream_size                                       : 37.7 MiB (0%)
Proportion_of_this_stream                         : 0.00078
Title                                             : Spanish (Latin American)
Language                                          : es
Language                                          : Spanish
Language                                          : Spanish
Language                                          : es
Language                                          : spa
Language                                          : es
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No

Text
----
Count                                             : 304
Count_of_stream_of_this_kind                      : 16
Kind_of_stream                                    : Text
Kind_of_stream                                    : Text
Stream_identifier                                 : 15
Stream_identifier                                 : 16
StreamOrder                                       : 18
ID                                                : 19
ID                                                : 19
Unique_ID                                         : 13516492667580207376
Format                                            : PGS
Format                                            : PGS
Commercial_name                                   : PGS
Codec_ID                                          : S_HDMV/PGS
Codec_ID_Info                                     : Picture based subtitle format used on BDs/HD-DVDs
Duration                                          : 6836872.000000
Duration                                          : 1 h 53 min
Duration                                          : 1 h 53 min 56 s 872 ms
Duration                                          : 1 h 53 min
Duration                                          : 01:53:56.872
Duration                                          : 01:53:56.872
Bit_rate                                          : 30843
Bit_rate                                          : 30.8 kb/s
Frame_rate                                        : 0.309
Frame_rate                                        : 0.309 FPS
Frame_count                                       : 2110
Count_of_elements                                 : 2110
Stream_size                                       : 26358990
Stream_size                                       : 25.1 MiB (0%)
Stream_size                                       : 25 MiB
Stream_size                                       : 25 MiB
Stream_size                                       : 25.1 MiB
Stream_size                                       : 25.14 MiB
Stream_size                                       : 25.1 MiB (0%)
Proportion_of_this_stream                         : 0.00052
Title                                             : Swedish
Language                                          : sv
Language                                          : Swedish
Language                                          : Swedish
Language                                          : sv
Language                                          : swe
Language                                          : sv
Default                                           : No
Default                                           : No
Forced                                            : No
Forced                                            : No

Menu
----
Count                                             : 125
Count_of_stream_of_this_kind                      : 1
Kind_of_stream                                    : Menu
Kind_of_stream                                    : Menu
Stream_identifier                                 : 0
Chapters_Pos_Begin                                : 101
Chapters_Pos_End                                  : 125
_00_00_00000                                      : en:Chapter 1
_00_05_09100                                      : en:Chapter 2
_00_08_43815                                      : en:Chapter 3
_00_14_29702                                      : en:Chapter 4
_00_21_25701                                      : en:Chapter 5
_00_24_06028                                      : en:Chapter 6
_00_28_25245                                      : en:Chapter 7
_00_34_21810                                      : en:Chapter 8
_00_39_40837                                      : en:Chapter 9
_00_44_10731                                      : en:Chapter 10
_00_48_47967                                      : en:Chapter 11
_00_52_47748                                      : en:Chapter 12
_00_56_18375                                      : en:Chapter 13
_01_00_17739                                      : en:Chapter 14
_01_04_41920                                      : en:Chapter 15
_01_09_13816                                      : en:Chapter 16
_01_15_13300                                      : en:Chapter 17
_01_19_14083                                      : en:Chapter 18
_01_23_59326                                      : en:Chapter 19
_01_28_06406                                      : en:Chapter 20
_01_33_07415                                      : en:Chapter 21
_01_39_19954                                      : en:Chapter 22
_01_44_22506                                      : en:Chapter 23
_01_46_13993                                      : en:Chapter 24
"""


EXAMPLE_SEARCH_PAYLOAD = MediaSearchPayload(
    imdb_id="tt6264654",
    tmdb_id="550988",
    tmdb_data={
        "adult": False,
        "backdrop_path": "/rOJb0yQOCny0bPjg8bCLw8DyAD7.jpg",
        "genre_ids": [35, 12, 878],
        "id": 550988,
        "original_language": "en",
        "original_title": "Movie Name",
        "overview": "A bank teller discovers he is actually a background player in an open-world video game, and decides to become the hero of his own story. Now, in a world where there are no limits, he is determined to be the guy who saves his world his way before it's too late.",
        "popularity": 99.24,
        "poster_path": "/6PFJrMvoQwBxQITLYHj09VeJ37q.jpg",
        "release_date": "{current_year}-08-11",
        "title": "Movie Name",
        "video": False,
        "vote_average": 7.5,
        "vote_count": 8924,
    },
    tvdb_id="57325",
    tvdb_data={
        "movie": {
            "id": 57325,
            "name": "Movie Name",
            "slug": "movie-name",
            "image": "https://artworks.thetvdb.com/banners/v4/movie/57325/posters/611467d60d4a3.jpg",
            "nameTranslations": [
                "eng",
                "pt",
                "fra",
                "por",
                "ita",
                "spa",
                "rus",
                "tur",
                "heb",
                "zho",
                "deu",
                "ell",
                "pol",
                "tha",
                "ara",
            ],
            "overviewTranslations": [
                "eng",
                "pt",
                "fra",
                "por",
                "ita",
                "spa",
                "rus",
                "tur",
                "heb",
                "zho",
                "deu",
                "ell",
                "pol",
                "tha",
                "ara",
            ],
            "aliases": [
                {"language": "fra", "name": "Free Player"},
                {"language": "spa", "name": "Movie Name: Tomando el control"},
            ],
            "score": 587783,
            "runtime": 115,
            "status": {
                "id": 5,
                "name": "Released",
                "recordType": "movie",
                "keepUpdated": True,
            },
            "lastUpdated": "2025-02-13 00:11:43",
            "year": "{current_year}",
        }
    },
    anilist_id=None,
    anilist_data=None,
    mal_id=None,
    title="Movie Name",
    year=current_year,
    original_title=None,
)
