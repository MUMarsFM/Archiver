__author__ = 'padraic'
import subprocess
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
import requests
import arrow
import json
import time
import threading
import logging
import multiprocessing
from pathlib import Path

basedir = Path('/var/www/archive.marsfm.ie/htdocs')

# TODO: Extend logging to provide show name in info
logging.basicConfig(level=logging.DEBUG,
                    format='[%(levelname)s]\t(%(threadName)-10s)\t%(message)s',
                    )


def clientServerOffset(schedulerTime):
    arrow.get(schedulerTime, 'YYYY-MM-DD HH:mm:ss')
    return arrow.get(schedulerTime, 'YYYY-MM-DD HH:mm:ss') - arrow.utcnow()


class Show():
    def __init__(self, show, offset):
        """
        Creates Show object from provided airtime metadata.
        :param show: dict
        """
        self.seriesTitle = show['name']
        self.id = show['id']
        # TODO: Seperate server times from locally adjusted times
        # TODO: Resync times before recording
        self.start = arrow.get(show['starts'], 'YYYY-MM-DD HH:mm:ss') - offset
        self.end = arrow.get(show['ends'], 'YYYY-MM-DD HH:mm:ss') - offset
        self.length = max((self.end - self.start).seconds, 1)
        self.title = " ".join([self.seriesTitle, self.start.format('YYYY-MM-DD')])
        self.filename = Path(self.title).with_suffix('.mp3')
        self.paths = [basedir / 'By Week' / self.start.floor('week').format('YYYY-MM-DD'),
                      basedir / 'By Show' / self.seriesTitle]

    def printInfo(self):
        # TODO: Less ugly formatting
        logging.info("Series Title: \t{} \n\t\t\t\t\t\tShow Title: \t{} \n\t\t\t\t\t\tShow Path: \t\t{}"
                     "\n\t\t\t\t\t\tShow Start: \t{} \n\t\t\t\t\t\tShow End: \t\t{} \n\t\t\t\t\t\tShow Length: "
                     "\t{} mins".format(self.seriesTitle, self.title, self.paths, self.start.ctime(),
                                        self.end.ctime(), self.length / 60))
        logging.debug(" ".join(["/usr/bin/cvlc", 'http://stream.marsfm.ie/listen', '--sout',
                                'file/mp3:{}'.format(self.paths[0] / self.filename),
                                '--stop-time={}'.format(self.length), '--run-time={}'.format(self.length),
                                'vlc://quit']))

    def _cvlcCall(self):
        """
        Connects to server and downloads stream for the duration of the Show.
        Process status code is returned
        """
        logging.info("Recording Start: {}".format(self.title))
        # TODO: Save files to folders sorted by week start
        grabber = subprocess.call(
            ["/usr/bin/cvlc", 'http://stream.marsfm.ie/listen', '--sout',
             'file/mp3:{}'.format(self.paths[0] / self.filename),
             '--stop-time={}'.format(self.length), '--run-time={}'.format(self.length), 'vlc://quit'],
            shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logging.info("Recording Ended: {}".format(self.title))
        self.setMetadata()
        # TODO: Link files to folders sorted by Series Name
        (self.paths[1] / self.filename).absolute().symlink_to((self.paths[0] / self.filename).absolute())

    def _multiprocessCvlcCall(self):
        multiprocessing.Process(name="VLC Recorder for {}".format(self.title), target=self._cvlcCall).start()

    def schedule_grab(self):
        delay = (self.start - arrow.utcnow()).seconds
        logging.info("Waiting {0} seconds to record {1}".format(delay, self.title))
        for folder in self.paths:
            if not folder.exists():
                logging.debug("Making Folder: {}".format(folder.absolute()))
                folder.mkdir(parents=True)
        threading.Timer(delay, self._multiprocessCvlcCall).start()

    def setMetadata(self):
        audio = MP3(str(self.paths[0] / self.filename), ID3=EasyID3)
        audio.update({'title': self.title, 'album': self.seriesTitle, 'artist': 'MarsFM',
                      'date': self.start.format('YYYY-MM-DD HH:mm'), 'genre': 'Radio'})
        audio.save()


def prepare_next_show():
    logging.info("Preparing Next Show for Capture")
    liveinfo = requests.get("http://airtime.marsfm.ie/api/live-info")
    liveinfojson = json.loads(liveinfo.text)

    myShow = Show(liveinfojson['nextShow'][0], clientServerOffset(liveinfojson['schedulerTime']))
    logging.debug(['Server Offset: ', str(clientServerOffset(liveinfojson['schedulerTime']))])
    logging.info("Candidate Found")
    myShow.printInfo()

    return myShow


def show_gatherer(prevStart):
    # TODO: Move timer from polling method
    nextShow = prepare_next_show()
    logging.debug("NextStart: {0}\tPrevStart: {1}\tResult: {2}".format(nextShow.start.floor('minute'), prevStart,
                                                                       nextShow.start > prevStart))
    if nextShow.start.floor('minute') > prevStart:
        logging.info("Candidate Accepted")
        nextShow.schedule_grab()
        return nextShow.start.floor('minute')
    else:
        logging.info("Candidate Declined")
        return prevStart


if __name__ == '__main__':
    logging.info("Starting StreamManager")
    prevStart = arrow.utcnow().floor('minute')
    while (True):
        prevStart = show_gatherer(prevStart)
        logging.info("Sleeping for 50")
        time.sleep(50)
