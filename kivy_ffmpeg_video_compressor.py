import os
import sys
import site
import threading
import subprocess
import shlex
from pathlib import Path

if getattr(sys, 'frozen', False) and not site.USER_BASE:
    # Kivy's Windows dependency packages assume USER_BASE is a string.
    site.USER_BASE = sys.prefix

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import StringProperty, BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.button import Button

KV = '''
<RootWidget>:
    orientation: 'vertical'
    padding: 12
    spacing: 10

    BoxLayout:
        size_hint_y: None
        height: '40dp'
        spacing: 8
        Label:
            text: 'Input video:'
            size_hint_x: None
            width: '110dp'
            halign: 'right'
            text_size: self.size
        TextInput:
            id: input_path
            text: root.input_path
            multiline: False
            readonly: True
        Button:
            text: 'Browse'
            size_hint_x: None
            width: '110dp'
            on_release: root.open_file_dialog()

    BoxLayout:
        size_hint_y: None
        height: '40dp'
        spacing: 8
        Label:
            text: 'Output file:'
            size_hint_x: None
            width: '110dp'
            halign: 'right'
            text_size: self.size
        TextInput:
            id: output_path
            text: root.output_path
            multiline: False
        Button:
            text: 'Auto name'
            size_hint_x: None
            width: '110dp'
            on_release: root.autofill_output_name()

    GridLayout:
        cols: 4
        size_hint_y: None
        height: '90dp'
        row_default_height: '40dp'
        row_force_default: True
        spacing: 8

        Label:
            text: 'Codec'
        Spinner:
            id: codec_spinner
            text: root.codec
            values: ['libx265', 'libx264']
            on_text: root.codec = self.text

        Label:
            text: 'Preset'
        Spinner:
            id: preset_spinner
            text: root.preset
            values: ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow']
            on_text: root.preset = self.text

        Label:
            text: 'CRF'
        TextInput:
            id: crf_input
            text: root.crf
            multiline: False
            input_filter: 'int'
            on_text: root.crf = self.text

        Label:
            text: 'Audio kbps'
        TextInput:
            id: audio_bitrate_input
            text: root.audio_bitrate
            multiline: False
            input_filter: 'int'
            on_text: root.audio_bitrate = self.text

    BoxLayout:
        size_hint_y: None
        height: '40dp'
        spacing: 8
        CheckBox:
            id: resize_checkbox
            size_hint_x: None
            width: '40dp'
            active: root.resize_enabled
            on_active: root.resize_enabled = self.active
        Label:
            text: 'Resize to 720p'
            size_hint_x: None
            width: '120dp'
        Widget:
        CheckBox:
            id: overwrite_checkbox
            size_hint_x: None
            width: '40dp'
            active: root.overwrite_output
            on_active: root.overwrite_output = self.active
        Label:
            text: 'Overwrite output'
            size_hint_x: None
            width: '130dp'

    BoxLayout:
        size_hint_y: None
        height: '44dp'
        spacing: 8
        Button:
            text: 'Build command'
            on_release: root.preview_command()
        Button:
            text: 'Compress video'
            disabled: root.is_running
            on_release: root.start_compression()
        Button:
            text: 'Stop'
            disabled: not root.is_running
            on_release: root.stop_compression()

    Label:
        text: 'Command preview:'
        size_hint_y: None
        height: '24dp'
        halign: 'left'
        text_size: self.size

    TextInput:
        text: root.command_preview
        readonly: True
        multiline: True
        size_hint_y: None
        height: '80dp'

    Label:
        text: root.status_text
        size_hint_y: None
        height: '28dp'
        halign: 'left'
        text_size: self.size

    TextInput:
        text: root.log_text
        readonly: True
        multiline: True
'''


class FileChooserPopup(Popup):
    def __init__(self, on_select, **kwargs):
        super().__init__(**kwargs)
        self.title = 'Select a video file'
        self.size_hint = (0.9, 0.9)
        self.auto_dismiss = False
        self.on_select = on_select

        layout = BoxLayout(orientation='vertical', spacing=8, padding=8)
        chooser = FileChooserListView(
            path=str(Path.home()),
            filters=['*.mp4', '*.mov', '*.mkv', '*.avi', '*.webm', '*.m4v', '*.flv']
        )
        layout.add_widget(chooser)

        button_row = BoxLayout(size_hint_y=None, height='44dp', spacing=8)
        cancel_btn = Button(text='Cancel')
        select_btn = Button(text='Select')

        cancel_btn.bind(on_release=lambda *_: self.dismiss())
        select_btn.bind(on_release=lambda *_: self._select(chooser.selection))

        button_row.add_widget(cancel_btn)
        button_row.add_widget(select_btn)
        layout.add_widget(button_row)
        self.content = layout

    def _select(self, selection):
        if selection:
            self.on_select(selection[0])
            self.dismiss()


class RootWidget(BoxLayout):
    input_path = StringProperty('')
    output_path = StringProperty('')
    codec = StringProperty('libx265')
    preset = StringProperty('slow')
    crf = StringProperty('30')
    audio_bitrate = StringProperty('64')
    resize_enabled = BooleanProperty(False)
    overwrite_output = BooleanProperty(False)
    command_preview = StringProperty('')
    log_text = StringProperty('ffmpeg output will appear here...')
    status_text = StringProperty('Idle')
    is_running = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.process = None
        self.worker_thread = None

    def open_file_dialog(self):
        popup = FileChooserPopup(on_select=self.set_input_file)
        popup.open()

    def set_input_file(self, file_path):
        self.input_path = file_path
        self.autofill_output_name()
        self.preview_command()

    def autofill_output_name(self):
        if not self.input_path:
            return
        src = Path(self.input_path)
        suffix = '_compressed.mp4' if self.codec in ('libx265', 'libx264') else '_compressed' + src.suffix
        self.output_path = str(src.with_name(src.stem + suffix))

    def build_ffmpeg_command(self):
        if not self.input_path:
            raise ValueError('Please select an input video.')
        if not self.output_path:
            raise ValueError('Please specify an output file.')

        ffmpeg_path = find_ffmpeg_executable()
        if ffmpeg_path is None:
            raise ValueError(
                'ffmpeg not found. Put ffmpeg.exe next to the app or install ffmpeg in PATH.'
            )

        cmd = [ffmpeg_path]
        cmd.append('-y' if self.overwrite_output else '-n')
        cmd.extend(['-i', self.input_path])

        if self.resize_enabled:
            cmd.extend(['-vf', 'scale=-2:720'])

        cmd.extend([
            '-c:v', self.codec,
            '-preset', self.preset,
            '-crf', self.crf,
            '-c:a', 'aac',
            '-b:a', f'{self.audio_bitrate}k',
            self.output_path,
        ])
        return cmd

    def preview_command(self):
        try:
            cmd = self.build_ffmpeg_command()
            self.command_preview = ' '.join(shlex.quote(part) for part in cmd)
            self.status_text = 'Command ready'
        except Exception as e:
            self.command_preview = ''
            self.status_text = str(e)

    def start_compression(self):
        try:
            cmd = self.build_ffmpeg_command()
        except Exception as e:
            self.status_text = f'Error: {e}'
            return

        self.is_running = True
        self.status_text = 'Compression running...'
        self.log_text = 'Starting ffmpeg...\n'
        self.command_preview = ' '.join(shlex.quote(part) for part in cmd)
        self.worker_thread = threading.Thread(target=self._run_ffmpeg, args=(cmd,), daemon=True)
        self.worker_thread.start()

    def _run_ffmpeg(self, cmd):
        try:
            startupinfo = None
            if sys.platform.startswith('win'):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                startupinfo=startupinfo,
            )

            for line in self.process.stdout:
                Clock.schedule_once(lambda dt, l=line: self.append_log(l))

            return_code = self.process.wait()
            if return_code == 0:
                Clock.schedule_once(lambda dt: self.finish_run(True, 'Compression completed successfully.'))
            else:
                Clock.schedule_once(lambda dt: self.finish_run(False, f'ffmpeg exited with code {return_code}.'))
        except Exception as e:
            Clock.schedule_once(lambda dt: self.finish_run(False, f'Execution error: {e}'))
        finally:
            self.process = None

    def append_log(self, line):
        self.log_text += line

    def finish_run(self, success, message):
        self.is_running = False
        self.status_text = message

    def stop_compression(self):
        if self.process and self.is_running:
            try:
                self.process.terminate()
                self.status_text = 'Stopping process...'
            except Exception as e:
                self.status_text = f'Error while stopping: {e}'


def shutil_which(cmd_name):
    from shutil import which
    return which(cmd_name)


def get_app_directory():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_ffmpeg_executable():
    app_dir = get_app_directory()
    candidates = []

    if sys.platform.startswith('win'):
        candidates.extend([
            app_dir / 'ffmpeg.exe',
            app_dir / 'ffmpeg' / 'ffmpeg.exe',
            app_dir / 'ffmpeg' / 'bin' / 'ffmpeg.exe',
        ])
    else:
        candidates.extend([
            app_dir / 'ffmpeg',
            app_dir / 'ffmpeg' / 'bin' / 'ffmpeg',
        ])

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return shutil_which('ffmpeg')


class VideoCompressorApp(App):
    title = 'FFmpeg Video Compressor'

    def build(self):
        Builder.load_string(KV)
        return RootWidget()


if __name__ == '__main__':
    VideoCompressorApp().run()
