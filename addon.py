import os
import os.path
import json
import xml.etree.ElementTree as et
import urlparse
import sys
import requests
import HTMLParser
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from shutil import copyfile
import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin
import sqlite3


plugin_url = sys.argv[0]
handle = int(sys.argv[1])
addon = xbmcaddon.Addon()

sources_path = os.path.join(addon.getAddonInfo("path"), "sources")
artworkPath = os.path.join(addon.getAddonInfo("path"), "artwork")

class RadioSource():
    def __init__(self, file):
        # Load XML
        xml = et.parse(os.path.join(sources_path, file + ".xml")).getroot()

        # Load source properties from XML
        self.name = xml.find("name").text
        self.streams = dict((int(stream.get("bitrate", default=0)), stream.text)
                            for stream in xml.findall("stream"))
        self.info = dict((child.tag, child.text) for child in xml
                         if child.tag not in ("name", "stream", "scraper"))
        self.url = "{0}?source={1}".format(plugin_url, file) 
        self.artworkThumb = artworkPath + '\\' + self.name + '\\thumb.jpg'
        self.artworkFanart = artworkPath + '\\' + self.name +  '\\fanart.jpg' 
        self.userName = addon.getSetting("username")
        
        # Load scraper properties
        if xml.find("scraper") is not None:
            self.scraper = dict((child.tag, child.text) for child in xml.find("scraper"))
            self.scraper["type"] = xml.find("scraper").get("type", default=None)
        else:
            self.scraper = None

    # Generate a Kodi list item from the radio source
    def list_item(self):
        li = xbmcgui.ListItem(self.name, iconImage="DefaultAudio.png", path=self.stream_url)
        li.setInfo("music", {"title": self.name,
                             "artist": self.info.get("tagline", None),
                             "genre": self.info.get("genre", None)
                             })
        li.setArt(self._build_art())
        return li

    # Start playing the radio source
    def play(self):  
        # Detect correct bitrate stream to play
        if addon.getSetting("bitrate") == "Maximum":
            if self.name == 'Primordial':
                self.stream_url = self.streams[max(self.streams.keys())] + self.userName    
            else:
                self.stream_url = self.streams[max(self.streams.keys())]
        else:
            if self.name == 'Primordial':
                self.stream_url = self.streams[max(self.streams.keys())] + self.userName
            else:
                max_bitrate = int(addon.getSetting("bitrate").split(" ")[0])
                bitrates = [bitrate for bitrate in self.streams.keys() if bitrate <= max_bitrate]
                self.stream_url = (self.streams[min(self.streams.keys())]
                                   if len(bitrates) == 0 else self.streams[max(bitrates)])

        # Create list item with stream URL and send to Kodi
            
        li = self.list_item()
        li.setPath(self.stream_url)
        RadioPlayer().play_stream(self)
        

    # Create dictionary of available artwork files to supply to list item
    def _build_art(self): 
        art = {"thumb": self.artworkThumb, "fanart": self.artworkFanart}

        return art


class RadioPlayer(xbmc.Player):
    def __init__(self):
        xbmc.Player.__init__(self)
        
    def play_stream(self, source): 
        
        response = requests.get(source.stream_url, stream=True, headers={'Connection':'close'},timeout=5.5)  
          
        if response.status_code == 200:
            response.close()
            xbmcplugin.setResolvedUrl(handle, False, source.list_item() )
            self.play(item=source.stream_url, listitem=source.list_item()) 
            xbmc.executebuiltin("Action(FullScreen)")
            if source.scraper is not None:
                info = RadioInfo(source)
                start_time = datetime.today()
                # Wait for playback to start, then loop until stopped
                while (self.isPlayingAudio() and xbmc.Player().getPlayingFile() == source.stream_url or datetime.today() <= start_time + timedelta(seconds=5)): 
                    info.update()
                    xbmc.sleep(1000)
            info.cleanup()  # Remove window properties on playback stop
            xbmc.Player().stop()
            xbmc.executebuiltin('xbmc.activatewindow(home)')
            exit()

        
        if response.status_code == 401:
            response.close()    
            line1 = "Your subscription may have expired"
            time = 10000
            xbmc.executebuiltin('Notification(%s, %s, %d, %s)'%('Error',line1, time, 'DefaultIconError.png'))
            addon.openSettings(1,1)
            xbmc.executebuiltin('xbmc.activatewindow(home)')
            exit()
        
        if  response.status_code != 401 and response.status_code != 200:
            response.close()
            line1 = "Primordial radio maybe down"
            time = 10000
            xbmc.executebuiltin('Notification(%s, %s, %d, %s)'%('Error',line1, time, 'DefaultIconError.png'))
            xbmc.executebuiltin('xbmc.activatewindow(home)')
            exit()

     

class RadioInfo():
    def __init__(self, source):
        self.window = xbmcgui.Window(10000)  # Attach properties to the home window
        self.window_properties = [] 

        self.scraper = source.scraper
        self.info = {"station": source.name}
        self.first_update = True
        self.next_update = datetime.today()
        self.delayed = False
        self.artworkThumb =source.artworkThumb
        self.scrapeArtwork = addon.getSetting("getartwork")
        self.scrapeGigs = addon.getSetting("getgigs")


    def update(self):  
        if self.next_update <= datetime.today():
            changed = self.get_now_playing()
            # Get track info if track has changed
            if changed:
                if self.scrapeArtwork == "true":
                    self.get_track_info()
                if self.scrapeGigs == "true":
                    self.get_gigs()
                    self.ShowGigs()
            # Apply delay so OSD update if required
            if changed and "delay" in self.scraper and not self.delayed and not self.first_update:
                self.next_update = datetime.today() + timedelta(seconds=int(self.scraper["delay"]))
                self.delayed = True
            # Set track info if no delay is required, or if a delay has already been applied
            elif changed or self.delayed:
                if self.scrapeArtwork == "true":
                    self.set_info()
                self.delayed = self.first_update = False
            # Wait as usual if track has not changed
            if not self.delayed:
                self.next_update = datetime.today() + timedelta(seconds=5)
                
    def ShowGigs(self):                
        if 'playingGig' in self.info and self.info["playingGig"] == "yes": 
            line1 = self.info["artist"]+" is playing live in concert soon"
            time = 20000
            xbmc.executebuiltin('Notification(%s, %s, %d, %s)'%('News',line1, time, 'DefaultAudio.png'))   
            del self.info["playingGig"]
            
    
    # Push track info to the skin as window properties
    def set_info(self): 
        url = self.info["thumb"]

        item = xbmcgui.ListItem()
        item.setPath(xbmc.Player().getPlayingFile())
        
        item.setArt({'thumb' : url, 'fanart' : url})
        xbmc.Player().updateInfoTag(item)
       
        #store image urls to cleanup later
        if self.info["thumb"] != self.artworkThumb:
            DBAddonCache().writeRow(self.info["thumb"])
               
    
    def get_gigs(self):
        try:          
            payload = {'artist': self.info["artist"]}
            response = requests.get("http://mobile-computer-repairs.co.uk/apis/primordial/getGig.php", params = payload)            
            if response.status_code == 200: 
                dataReturn = response.json()
                if "ticket" in dataReturn: 
                    self.info["playingGig"] = dataReturn['ticket']['isGig']
                            
        except: pass

    def cleanup(self):
        for name in self.window_properties:
            self.window.clearProperty(name)

    def get_now_playing(self):
        if self.first_update: 
            while not xbmc.Player().isPlayingAudio():
                xbmc.sleep(1000)
        lastTrackQuery = self.info.get("title", "") + self.info.get("artist", "")
        track_id = self.id_track()
        # Return True if track info has changed
        return lastTrackQuery != self.id_track()   
        
    # Retrieve additional track info from web
    def get_track_info(self):
        # Reset track information before updating  

        if 'thumb' in self.info:
            self.info["oldThumb"] = self.info["thumb"]
            
        try:
            url = 'http://mobile-computer-repairs.co.uk/apis/primordial/getInfo.php?'    
            payload = (('artist', self.info["artist"]), ('track', self.info["title"]))
            response = requests.get("https://mobile-computer-repairs.co.uk/apis/primordial/getInfo.php", params = payload)   
            if response.status_code == 200: 
                dataReturn = response.json()
                if "track" in dataReturn:
                    track_info = dataReturn["track"]
                    if "imageUrl" in track_info and len(track_info['imageUrl']) > 0:
                        self.info["thumb"] = track_info['imageUrl']
                else: 
                    self.info["thumb"] = self.artworkThumb
                
        except: pass
        
        if 'thumb' in self.info:
            if 'oldThumb' in self.info and self.info["oldThumb"] == self.info["thumb"]:
                self.info["thumb"] = self.artworkThumb
        else:     
            self.info["thumb"] = self.artworkThumb

    def id_track(self):
        match = str(xbmc.Player().getMusicInfoTag().getTitle())
        if len(match) > 0 and " - " in match:
            self.info["artist"], self.info["title"] = match.split(" - ")
               
        return self.info.get("title", "") + self.info.get("artist", "")


class DBAddonCache():
    def __init__(self):
        self.db = os.path.join(addon.getAddonInfo("path"), "cache\\")+"ImageCache.db"
        self.conn = None

    def __connect__(self):        
        self.conn = sqlite3.connect(self.db)
        self.cur = self.conn.cursor()

    def __disconnect__(self):
        self.conn.close()
        
    def writeRow(self, data):
        self.__connect__()
        self.cur.execute('INSERT INTO location values (NULL,?)', (data,))
        self.conn.commit()
        self.__disconnect__()

    def fetchAll(self):
        self.__connect__()
        self.cur.execute("SELECT url FROM location")
        rows = self.cur.fetchall()
        self.__disconnect__()
        return rows
        
    def dropAll(self):
        self.__connect__()
        dropTable = "DROP TABLE IF EXISTS location"
        self.cur.execute(dropTable)
        self.__disconnect__()
    
    def create(self):
        self.__connect__()
        createTable =   """CREATE TABLE IF NOT EXISTS location( 
                            id INTEGER NOT NULL DEFAULT 1 PRIMARY KEY AUTOINCREMENT UNIQUE,
                            url TEXT NOT NULL
                        );"""
                        
        self.cur.execute(createTable)
        self.__disconnect__()
        
        
class DBKodiCache():  
    def __init__(self):
        self.db = os.path.join(xbmc.translatePath("special://database/"), "Textures13.db")
        self.conn = None

    def __connect__(self):    
        self.conn = sqlite3.connect(self.db)
        self.cur = self.conn.cursor()

    def __disconnect__(self):
        self.conn.close()
       
    def fetchAllLoop(self, data):
        self.__connect__()
        chacehListLocation = []
        chacehListIndex = []
        for boglins in data:
            self.cur.execute("SELECT * FROM texture WHERE url=?", (boglins[0],))
            row = self.cur.fetchall() 
            if row:
                chacehListIndex.append(row[0][0])
                chacehListLocation.append(row[0][2])
 
        if chacehListIndex:
            self.deleteRows(chacehListIndex, chacehListLocation)
    
    def deleteRows(self,index, location):        
        query = "DELETE FROM texture WHERE id IN ({})".format(", ".join("?" * len(index)))
        self.cur.execute(query, index)
        self.conn.commit()    
        self.__disconnect__()
        self.deleteShit(location)
        
        
    def deleteShit(self, location):
        for loc in location:
            fileDelte = os.path.join(xbmc.translatePath("special://thumbnails/"))
            imageToDelte = fileDelte + loc
            if os.path.exists(imageToDelte):
                os.remove(imageToDelte)
        #os.remove(os.path.join(addon.getAddonInfo("path"), "cache\\")+"ImageCache.db")
 
 



def ping(host):
    """
    Returns True if host responds to a ping request
    """
    import subprocess, platform

    # Ping parameters as function of OS
    ping_str = "-n 1" if  platform.system().lower()=="windows" else "-c 1"
    args = "ping " + " " + ping_str + " " + host
    need_sh = False if  platform.system().lower()=="windows" else True

    # Ping
    return subprocess.call(args, shell=need_sh) == 0
    



    
count = 0
checkInternet = ping('8.8.8.8')
while count < 5 and checkInternet is not True:
    xbmc.sleep(2000)
    count += 1
    
if checkInternet:
    cleanUpOld = DBAddonCache().fetchAll()
    if cleanUpOld:
        DBKodiCache().fetchAllLoop(cleanUpOld)
        DBAddonCache().dropAll()
        DBAddonCache().create()

    RadioSource('primordial').play()   
        
else: 
    line1 = "Check your internet connection"
    time = 10000
    xbmc.executebuiltin('Notification(%s, %s, %d, %s)'%('Error',line1, time, 'DefaultIconError.png'))  
    quit()
   

