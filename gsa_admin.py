#!/usr/bin/python
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# This code is not supported by Google
#
"""Classes for administering the Google Search Appliance.

Currently, the classes available can be used to import/export/rewrite
the config file. This module is designed to be expandable so that
other functionality can be easily included.

gsaConfig: Class for handling XML from GSA export/import.
gsaWebInterface: Class for interacting with GSA Web Interface.

Example usage:

1. Export the config file:

gsa_admin.py -n <host> --port 8000 -u admin -p <pw> -e --sign-password
hellohello -o ~/tmp/o.xml -v

2. Make a change to the config file and sign:

./gsa_admin.py -n <host> -u admin -p <pw> -s --sign-password hellohello
-f ~/tmp/o.xml -v -o ~/tmp/o2.xml

3. Import the new config file:

./gsa_admin.py -n <host> --port 8000 -u admin -p <pw> -i --sign-password
hellohello -f ~/tmp/o2.xml -v

Note that you must use the same password to sign a file that you used
when exporting. You will get an error when importing if you do not do
this.

4. Export all the URLs to a file:

./gsa_admin.py --hostname=<host> --username=admin
--password=<pw> --all_urls --output=/tmp/all_urls

5. Retrieve GSA^n (mirroring) status from the admin console
./gsa_admin.py -z -n <host> -u admin -p <pw>

6. Trigger database synchronization
./gsa_admin.py -n YOUR_GSA --port 8000 -u admin -p YOUR_PASSWORD --database_sync --sources=DB_NAME

7. Run custom support script provided by Google Support
./gsa_admin.py -n YOUR_GSA --port 8000 -u admin -p YOUR_PASSWORD -m -f ./sscript.txt -o ./out.txt -t 300

TODO(jlowry): add in functionality from adminconsole.py:
pause/resume crawl, get crawl status, shutdown.
"""

__author__ = "alastair@mcc-net.co.uk (Alastair McCormack)"


import cgi
import os.path
import logging
import sys
import xml.dom.minidom
import hashlib
import hmac
import json
import codecs
import urllib2
import urllib
import cookielib
import re
import time
import urlparse
from optparse import OptionParser, OptionGroup

# Required for utf-8 file compatibility
reload(sys)
sys.setdefaultencoding("utf-8")
del sys.setdefaultencoding

class NullHandler(logging.Handler):
    def emit(self, record):
        pass

DEFAULTLOGLEVEL=logging.DEBUG
log = logging.getLogger(__name__)
log.addHandler(NullHandler())

class gsaConfig:
  "Google Search Appliance XML configuration tool"

  configXMLString = None

  def __init__(self, fileName=None):
    if fileName:
      self.openFile(fileName)

  def __str__(self):
    return self.configXMLString

  def openFile(self, fileName):
    "Read in file as string"
    if not os.path.exists(fileName):
      log.error("Input file does not exist")
      sys.exit(1)
    configXMLdoc = open(fileName)
    self.configXMLString = configXMLdoc.read()
    configXMLdoc.close()

  def setXMLContents(self, xmlString):
    "Sets the runtime XML contents"
    self.configXMLString = xmlString.encode("utf-8")
    #log.warning("Signature maybe invalid. Please verify before uploading or saving")

  def getXMLContents(self):
    "Returns the contents of the XML file"
    return self.configXMLString.encode("utf-8")

  def computeSignature(self, password):
    configXMLString = self.getXMLContents()
    # ugly removal of spaces because minidom cannot remove them automatically when removing a node
    configXMLString = re.sub('          <uam_dir>', '<uam_dir>', configXMLString)
    configXMLString = re.sub('</uam_dir>\n', '</uam_dir>', configXMLString)

    doc = xml.dom.minidom.parseString(configXMLString)
    # Remove <uam_dir> node because new GSAs expect so
    uamdirNode = doc.getElementsByTagName("uam_dir").item(0)
    uamdirNode.parentNode.removeChild(uamdirNode)

    uardataNode = doc.getElementsByTagName("uar_data").item(0)
    uardataB64contents = uardataNode.firstChild.nodeValue.strip()+'\n'
    if uardataB64contents != "\n":
      log.debug("UAR data contains data.  Must be 7.0 or newer")
      # replace <uar_data> node with "/tmp/tmp_uar_data_dir,hash"
      # 1: Strip additional spaces at the end but we need the new line
      #     to compute hash.
      #    "AAAAAAAAAA==\n          ]]></uar_data>" <-- 10 spaces
      uardataHash = hmac.new(password, uardataB64contents, hashlib.sha1).hexdigest()
      # 2: Replace to <dummy file name, hash> with additional whitespaces.
      uardataNode.firstChild.nodeValue = ("\n/tmp/tmp_uar_data_dir,"
          + "%s\n          ") % (''+uardataHash)
      log.debug("uar_data is replaced to %s" % uardataNode.toxml())
    # Get <config> node
    configNode = doc.getElementsByTagName("config").item(0)
    # get string of Node and children (as utf-8)
    configNodeXML = configNode.toxml()
    # Create new HMAC using user password and configXML as sum contents
    return hmac.new(password, configNodeXML, hashlib.sha1).hexdigest()

  def sign(self, password):
    computedSignature=self.computeSignature(password)
    configXMLString = self.getXMLContents()
    doc = xml.dom.minidom.parseString(configXMLString)

    # Get <signature> node
    signatureNode = doc.getElementsByTagName("signature").item(0)
    signatureCDATANode = signatureNode.firstChild
    # Set CDATA/Text area to new HMAC
    signatureCDATANode.nodeValue = computedSignature
    self.setXMLContents(doc.toxml())

  def writeFile(self, filename):
    if os.path.exists(filename):
      log.error("Output file exists")
      sys.exit(1)
    doc = xml.dom.minidom.parseString(self.configXMLString)
    outputXMLFile = codecs.open(filename, 'w', "utf-8")
    log.debug("Writing XML to %s" % filename)
    # GSA newer than 6.? expects '<eef>' to be on the second line.
    outputXMLFile.write(doc.toxml().replace("<eef>", "\n<eef>", 1))

  def verifySignature(self, password):
    computedSignature = self.computeSignature(password)
    configXMLString = self.getXMLContents()
    doc = xml.dom.minidom.parseString(configXMLString)

    # Get <signature> node
    signatureNode = doc.getElementsByTagName("signature").item(0)
    signatureCDATANode = signatureNode.firstChild
    signatureValue = signatureNode.firstChild.nodeValue
    # signatureValue may contain whitespace and linefeeds so we'll just ensure that
    # our HMAC is found within

    if signatureValue.count(computedSignature) :
      log.debug("Signature matches")
      return 1
    else:
      log.debug("Signature does not match %s vs %s" %
                (signatureValue, computedSignature))
      return None


class gsaWebInterface:
  "Google Search Appliance Web Interface Wrapper)"

  baseURL = None
  username = None
  password = None
  hostName = None
  loggedIn = None
  _url_opener = None

  def __init__(self, hostName, username, password, port=8000):
    self.baseURL = 'http://%s:%s/EnterpriseController' % (hostName, port)
    self.hostName = hostName
    self.username = username
    self.password = password
    # build cookie jar for this web instance only. Should allow for GSAs port mapped behind a reverse proxy.
    cookieJar = cookielib.CookieJar()
    self._url_opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cookieJar))

  def _openurl(self, request):
    """Args:
      request: urllib2 request object or URL string.
    """
    return self._url_opener.open(request)

  def _encode_multipart_formdata(self, fields, files):
    """
    fields: a sequence of (name, value) elements for regular form fields.
    files: a sequence of (name, filename, value) elements for data to be uploaded as files
    """
    BOUNDARY = '----------ThIs_Is_tHe_bouNdaRY_$'
    CRLF = '\r\n'
    lines = []
    for (key, value) in fields:
      lines.append('--' + BOUNDARY)
      lines.append('Content-Disposition: form-data; name="%s"' % key)
      lines.append('')
      lines.append(value)
    for (key, filename, value) in files:
      lines.append('--' + BOUNDARY)
      lines.append('Content-Disposition: form-data; name="%s"; filename="%s"' % (key, filename))
      lines.append('Content-Type: text/xml')
      lines.append('')
      lines.append(value)
    lines.append('--' + BOUNDARY + '--')
    lines.append('')
    body = CRLF.join(lines)
    content_type = 'multipart/form-data; boundary=%s' % BOUNDARY
    return content_type, body

  def _login(self):
    if not self.loggedIn:
      log.debug("Fetching initial page for new cookie")
      self._openurl(self.baseURL)
      request = urllib2.Request(self.baseURL,
                                urllib.urlencode(
          {'actionType' : 'authenticateUser',
           # for 7.0 or older
           'userName' : self.username,
           'password' : self.password,
           # for 7.2 and newer.  Having both doesn't hurt
           'reqObj' : json.dumps([None, self.username, self.password, None, 1]),
           }))

      log.debug("Logging in as %s..."  % self.username)
      result = self._openurl(request)
      resultString = result.read()
      # Pre 7.2 has "Google Search Appliance  &gt;Home"
      # 7.2 and later returns JSON like object
      home = re.compile("Google Search Appliance\s*&gt;\s*Home")
      home72 = re.compile('"xsrf": \[null,"security_token","')
      if  home.search(resultString):
        log.debug("7.0 or older")
        self.is72 = False
      elif home72.search(resultString):
        log.debug("7.2 or newer")
        # The first line is junk to prevent some action on browsers:  )]}',
        # Just skip it.
        response = json.loads(resultString[5:])
        log.info("Security token is: " + response["xsrf"][2])
        self.is72 = True
      else:
        log.error("Login failed: " + resultString)
        sys.exit(2)

      log.debug("Successfully logged in")
      self.loggedIn = True

  def _logout(self):
    request = urllib2.Request(self.baseURL + "?" + urllib.urlencode({'actionType' : 'logout'}))
    self._openurl(request)
    self.loggedIn = False

  def __del__(self):
    self._logout()

  def importConfig(self, gsaConfig, configPassword):
    fields = [("actionType", "importExport"), ("passwordIn", configPassword),
        ("import", " Import Configuration ")]

    files = [("importFileName", "config.xml", gsaConfig.getXMLContents() )]
    content_type, body = self._encode_multipart_formdata(fields,files)
    headers = {'User-Agent': 'python-urllib2', 'Content-Type': content_type}

    self._login()
    security_token = self.getSecurityToken('cache')
    request = urllib2.Request(self.baseURL + "?" +
                              urllib.urlencode({'actionType': 'importExport',
                                                'export': ' Import Configuration ',
                                                'security_token' : security_token,
                                                'a' : '1',
                                                'passwordIn': configPassword}),
                              body, headers)
    log.info("Sending XML...")
    result = self._openurl(request)
    content = result.read()
    if content.count("Invalid file"):
      log.error("Invalid configuration file")
      sys.exit(2)
    elif content.count("Wrong passphrase or the file is corrupt"):
      log.error("Wrong passphrase or the file is corrupt. Try ")
      sys.exit(2)
    elif content.count("Passphrase should be at least 8 characters long"):
      log.error("Passphrase should be at least 8 characters long")
      sys.exit(2)
    elif content.count("File does not exist"):
      log.error("Configuration file does not exist")
      sys.exit(2)
    elif not content.count("Configuration imported successfully"):
      log.error("Import failed")
      sys.exit(2)
    else:
      log.info("Import successful")

  def exportConfig(self, configPassword):
    self._login()
    security_token = self.getSecurityToken('cache')
    request = urllib2.Request(self.baseURL + "?" +
                              urllib.urlencode({'actionType': 'importExport',
                                                'export': ' Export Configuration ',
                                                'security_token': security_token,
                                                'a': '1',
                                                'password1': configPassword,
                                                'password2': configPassword}))

    log.debug("Fetching config XML")
    result = self._openurl(request)
    content = result.read()
    if content.count("Passphrase should be at least 8 characters long"):
      log.error("Passphrase should be at least 8 characters long. You entered: '%s'" % (configPassword))
      sys.exit(2)
    gsac = gsaConfig()
    log.debug("Returning gsaConfig object")
    gsac.setXMLContents(content)
    return gsac

  def getSecurityTokenFromContents(self, content):
    """Gets the value of the security_token hidden form parameter.

    Args:
      content: a string containing HTML contents

    Returns:
      A long string, required as a parameter when submitting the form.
      Returns an empty string if security_token does not exist.
    """
    token_re = re.compile('name="security_token"[^>]*value="([^"]*)"', re.I)
    match = token_re.search(content)
    if match:
      security_token = match.group(1)
      log.debug('Security token is: %s' % (security_token))
      return security_token
    else:
      return ""

  def getSecurityToken(self, actionType):
    """Gets the value of the security_token hidden form parameter.

    Args:
      actionType: a string, used to fetch the Admin Console form.

    Returns:
      A long string, required as a parameter when submitting the form.
      Returns an empty string if security_token does not exist.
    """
    self._login()
    # request needs to be a GET not POST
    url = "%s?actionType=%s&a=1" % (self.baseURL, actionType)
    log.debug('Fetching url: %s' % (url))
    result = self._openurl(url)
    content = result.read()
    token_re = re.compile('name="security_token"[^>]*value="([^"]*)"', re.I)
    match = token_re.search(content)
    if match:
      security_token = match.group(1)
      log.debug('Security token is: %s' % (security_token))
      return security_token
    else:
      return ""

  def setAccessControl(self, maxhostload=10, urlCacheTimeout=3600):
    # Tested on 6.8. Will not work on previous versions unless the form
    # parameters are modified.
    self._login()
    security_token = self.getSecurityToken('cache')
    # Sample body of a POST from a 6.8 machine:
    #  security_token=Vaup237Rd5jXE6ZC0Iy6BeVo4h0%3A1290533850660&
    #  actionType=cache&
    #  basicAuthChallengeType=auto&
    #  authzServiceUrl=&
    #  overallAuthzTimeout=20.0&
    #  requestBatchTimeout=5.0&
    #  singleRequestTimeout=2.5&
    #  maxHostload=10&
    #  urlCacheTimeout=3600&
    #  saveSettings=Save+Settings
    request = urllib2.Request(self.baseURL,
                              urllib.urlencode({'security_token': security_token,
                                                'a': '1',
                                                'actionType': 'cache',
                                                'basicAuthChallengeType': 'auto',
                                                'authzServiceUrl': '',
                                                'queryProcessingTime': '20.0',
                                                'requestBatchTimeout': '5.0',
                                                'singleRequestTimeout': '2.5',
                                                'maxHostload': maxhostload,
                                                'urlCacheTimeout': urlCacheTimeout,
                                                'saveSettings': 'Save Settings'}))
    result = self._openurl(request)
    # Form submit did not work if content contains this string: "Forgot Your Password" or
    # <font color="red"> unless multiple users are logged in.
    # content = result.read()
    # log.info(content)

  def _unescape(self, s):
    s = s.replace('&amp;', '&')
    return s

  def syncDatabases(self, database_list):
    """Sync databases in the GSA.

    Args:
      database_list: a List of String, a list of database name to sync
    """
    self._login()
    for database in database_list:
      log.info("Syncing %s ..." % database)
      param = urllib.urlencode({"actionType": "syncDatabase",
                                "entryName": database})
      request = urllib2.Request(self.baseURL + "?" + param)
      try:
        result = self._openurl(request)
      except:
        log.error("Unable to sync %s properly" % database)

  def exportAllUrls(self, out):
    """Export the list of all URLs

    Args:
      out: a File, the file to write to.
    """
    self._login()
    security_token = self.getSecurityToken('exportAllUrls')
    log.info("Generating the list of all URLs")
    if self.is72:
      param = urllib.urlencode({'security_token' : security_token,
                                'a'              : '1',
                                'filterMode'     : 'all_urls',
                                'goodURLs'       : '',
                                'actionType'     : 'exportAllUrls',
                                'exportAction'   : 'generate',
                                'generate'       : 'Generate the gzip file',
                                })
    else:
      param = urllib.urlencode({'actionType' : 'exportAllUrls',
                                'action' : 'generate',
                                'goodURLs' : '',
                                'security_token' : security_token,
                                'filterMode' : 'all_urls'})
    request = urllib2.Request(self.baseURL, param)

    try:
      result = self._openurl(request)
      seurity_token = self.getSecurityTokenFromContents(result.read())
      #output = result.read()
      #out.write(output)
    except Exception, e:
      log.error("Unable to generate the list of All URLs")
      log.error(e)

    while 1:
      param = urllib.urlencode({'actionType' : 'exportAllUrls',
                                'security_token' : security_token,
                                'a' : '1'})
      request = urllib2.Request(self.baseURL, param)
      result = self._openurl(request)
      if self.is72:
        generating_msg = '<input type="submit" name="generate" id="generate" disabled class="hb-r-N nd-Ld-re" value="Generating...">'
      else:
        generating_msg = '<input type="submit" name="generate" id="generate" disabled value="Generating...">'
      content = result.read()
      security_token = self.getSecurityTokenFromContents(content)
      if content.find(generating_msg) == -1:
        log.info("The list has been generated.")
        log.debug("content is " + content)
        break
      else:
        log.info("Still generating the list.  Sleep for 10 seconds...")
        time.sleep(10)

    # 7.0 or older default
    exportActionStr = 'action'
    if self.is72:
      exportActionStr = 'exportAction'
    log.info("Downloading the list of all URLs")
    param = urllib.urlencode({'actionType' : 'exportAllUrls',
                              exportActionStr : 'download',
                              'security_token' : security_token,
                              'a' : '1'})
    request = urllib2.Request(self.baseURL, param)
    try:
      result = self._openurl(request)
      output = result.read()
      out.write(output)
    except Exception, e:
      log.error("Unable to download the list")
      log.error(e)

  def exportKeymatches(self, frontend, out):
    """Export all keymatches for a frontend.

    Args:
      frontend: a String, the frontend name.
      out: a File, the file to write to.
    """
    self._login()
    security_token = self.getSecurityToken('viewFrontends')
    log.info("Retrieving the keymatch file for %s" % frontend)
    param = urllib.urlencode({'actionType' : 'frontKeymatchImport',
                              'security_token' : security_token,
                              'a' : '1',
                              'frontend' : frontend,
                              'frontKeymatchExportNow': 'Export KeyMatches Now',
                              'startRow' : '1', 'search' : ''})
    if self.is72:
      request = urllib2.Request(self.baseURL, param)
    else:
      request = urllib2.Request(self.baseURL + "?" + param)
    try:
      result = self._openurl(request)
      output = result.read()
      out.write(output)
    except Exception, e:
      log.error("Unable to retrieve Keymatches for %s" % frontend)
      log.error(e)
  def exportSynonyms(self, frontend, out):
    """Export all Related Queries for a frontend.

    Args:
      frontend: a String, the frontend name.
      out: a File, the file to write to.
    """
    self._login()
    security_token = self.getSecurityToken('viewFrontends')
    log.info("Retrieving the Related Queries file for %s" % frontend)
    param = urllib.urlencode({'actionType' : 'frontSynonymsImport',
                              'security_token' : security_token,
                              'a' : '1',
                              'frontend' : frontend,
                              'frontSynonymsExportNow': 'Export Related Queries Now',
                              'startRow' : '1', 'search' : ''})
    if self.is72:
      request = urllib2.Request(self.baseURL, param)
    else:
      request = urllib2.Request(self.baseURL + "?" + param)
    try:
      result = self._openurl(request)
      output = result.read()
      out.write(output)
    except:
      log.error("Unable to retrieve Related Queries for %s" % frontend)

  def getAllUrls(self, out):
    """Retrieve all the URLs in the Crawl Diagnostics.

       The URLs can be extracted from the crawl diagnostics URL with
       actionType=contentStatus.  For example, the URL in link

       /EnterpriseController?actionType=contentStatus&...&uriAt=http%3A%2F%2Fwww.google.com%2F

       is http://www.google.com/

       We only follow crawl diagnostic URLs that contain actionType=contentStatus
    """
    self._login()
    log.debug("Retrieving URLs from Crawl Diagostics")
    tocrawl = set([self.baseURL + '?actionType=contentDiagnostics&sort=crawled'])
    crawled = set([])
    doc_urls = set([])
    href_regex = re.compile(r'<a href="(.*?)"')
    while 1:
      try:
        log.debug('have %i links to crawl' % len(tocrawl))
        crawling = tocrawl.pop()
        log.debug('crawling %s' % crawling)
      except KeyError:
        raise StopIteration
      url = urlparse.urlparse(crawling)
      request = urllib2.Request(crawling)
      try:
        result = self._openurl(request)
      except:
        print 'unable to open url'
        continue
      content = result.read()
      crawled.add(crawling)

      links = href_regex.findall(content)
      log.debug('found %i links' % len(links))
      for link in (links.pop(0) for _ in xrange(len(links))):
        log.debug('found a link: %s' % link)
        if link.startswith('/'):
          link = url[0] + '://' + url[1] + link
          link = self._unescape(link)
          if link not in crawled:
            log.debug('this links has not been crawled')
            if (link.find('actionType=contentDiagnostics') != -1 and
                 link.find('sort=excluded') == -1 and
                 link.find('sort=errors') == -1 and
                 link.find('view=excluded') == -1 and
                 link.find('view=successful') == -1 and
                 link.find('view=errors') == -1):
              tocrawl.add(link)
              #print 'add this link to my tocrawl list'
            elif link.find('actionType=contentStatus') != -1:
              # extract the document URL
              doc_url = ''.join(cgi.parse_qs(urlparse.urlsplit(link)[3])['uriAt'])
              if doc_url not in doc_urls:
                out.write(doc_url + '\n')
                doc_urls.add(doc_url)
                if len(doc_urls) % 100 == 0:
                  print len(doc_urls)
            else:
              log.debug('we are not going to crawl this link %s' % link)
              pass
          else:
            log.debug('already crawled %s' % link)
            pass
        else:
          log.debug('we are not going to crawl this link %s' % link)
          pass

  def getStatus(self):
    """Get System Status and mirroring if enabled

      The GSA sends out daily email but it doesn't inlcude mirroing status
      Temporary solution -- only tested with 6.2.0.G.44
    """

    self._login()
    log.info("Retrieving GSA^n network diagnostics status from: %s", self.hostName)
    request = urllib2.Request(self.baseURL + "?" +
                              urllib.urlencode({'a': 1,
                                                'actionType': 'gsanDiagnostics'}))

    result = self._openurl(request)
    content = result.read()
    nodes = re.findall("row.*(<b>.*</b>)", content)
    if self.is72 and "nd-ue-re" in content:
      print "This is 7.2 or newer.  Just printing the whole output contents."
      print content
      return
    if not nodes:
      log.error("Could not find any replicas...\n%s" % content)
      exit(3)

    log.debug(nodes)
    connStatus = re.findall("(green|red) button", content)
    log.debug(connStatus)

    numErrs = 0
    for index, val in enumerate(connStatus):
      if val == "green":
        connStatus[index] = "OK"
      else:
        connStatus[index] = "ERROR - Test FAILED"
        numErrs += 1

    pos = 0
    print "========================================="
    for node in nodes:
      print "Node: " +  re.sub(r'<[^<]*?/?>', '', node)
      print "Ping Status: " + connStatus[0+pos]
      print "Stunnel Listener up: ", connStatus[1+pos]
      print "Stunnel Connection: ", connStatus[2+pos]
      print "PPP Connection Status: ", connStatus[3+pos]
      print "Application Connection Status: ", connStatus[4+pos]
      pos += 5
      if pos < len(connStatus):
        print "----------------------------------------"
    print "========================================="
    if numErrs:
      print numErrs,  "ERROR(s) detected. Please review mirroing status"
    else:
      print "All Tests passes successfully"
    print "=========================================\n"

    detailStats = re.search("Detailed Status(.*)\"Balls\">", content, re.DOTALL)
    if detailStats:
    #Check if this is primary node and display sync info
      detailStats = re.sub(r'</td>\n<td ', ': <', detailStats.group(), re.DOTALL)
      detailStats = re.sub(r'</td> <td ',' | <', detailStats, re.DOTALL)
      detailStats = re.sub(r'<[^<]*?/?>', '', detailStats)

      prettyStats = detailStats.split("\n")
      for row in prettyStats:
        cols = row.split(": ")
        if len(cols) > 1:
          cols[0] = cols[0] + ":" + " " * (40 - len(cols[0]))
        print ''.join(cols)
      print "==========================================================="

  def getCollection (self,collection):
    """Get Collection statistics for daily processing."""
    self._login()
    log.debug("Retrieving GSA's collection information from: %s, collection name %s",
              self.hostName, collection)
    request = urllib2.Request(self.baseURL + "?" +
                              urllib.urlencode({'actionType': 'contentDiagnostics',
                                                'sort': 'crawled',
                                                'collection': collection}))
    result = self._openurl(request)
    content = result.read()
    urlall = re.findall("view=all.>(.*)</a>",content)
    urlsuccessful = re.findall("view=successful.>(.*)</a>",content)
    urlerrors = re.findall("view=errors.>(.*)</a>",content)
    urlexcluded = re.findall("view=excluded.>(.*)</a>",content)
    numsurls = 0
    numeurls = 0
    for i in range(len(urlall)):
      log.debug("URL %s Successful URLs %s Errored URLs %s ",urlall[i], urlsuccessful[i], urlerrors[i])
      numsurls = numsurls + int(urlsuccessful[i].replace(",", ""))
      numeurls = numeurls + int(urlerrors[i].replace(",", ""))
      log.debug("Collection Totals: %s URLs, %s Error URLs", numsurls, numeurls)
    # Here you can plug any type of MySQL logging method/etc

  def runCusSscript(self, sscript_file, out_fd, timeout=180):
    """Run custom support script.

       Args:
         sscript_file: file containing the encrypted custom support script
         out_fd: file descriptor for the output file
         timeout: timeout value in secs to wait for support script to complete
    """
    if not os.path.exists(sscript_file):
      log.error("File %s does not exist", sscript_file)
      sys.exit(1)
    ssfd = open(sscript_file)
    ss_str = ssfd.read()
    ssfd.close()

    self._login()
    security_token = self.getSecurityToken('cache')
    fields = [('security_token', security_token),
              ('actionType', 'supportScripts'),
              ('action', 'run'),
              ('scriptType', 'customFile'),
              ('run', 'Run support script')]
    files = [('importFileName', 'cus_sscript_file', ss_str)]
    content_type, body = self._encode_multipart_formdata(fields,files)
    headers = {'User-Agent': 'python-urllib2', 'Content-Type': content_type}
    request = urllib2.Request(self.baseURL, body, headers)
    log.info("Submitting support script...")
    result = self._openurl(request)
    content = result.read()
    if content.count("Support script submission failed"):
      log.error("Support script submission failed")
      sys.exit(2)
    log.info("Support script submitted")

    # support script submitted, check whether output is available
    
    param = urllib.urlencode({"actionType": "supportScripts"})
    request = urllib2.Request(self.baseURL + "?" + param)
    tm = 0
    sleeptime = 4
    while True:
      result = self._openurl(request)
      content = result.read()
      if not content.count("A support script is running"):
        log.info("output is ready")
        break
      log.info("Support script still running...")
      time.sleep(sleeptime)
      tm += sleeptime
      if tm > timeout:
        log.error("Support script timed out")
        sys.exit(1)

    # support script run is done, download the output
    param = urllib.urlencode({"actionType": "supportScripts",
                              "security_token": security_token,
                              "download": "Download results from previous run",
                              "action": "download"})
    request = urllib2.Request(self.baseURL, param)
    result = self._openurl(request)
    content = result.read()
    if content.count("Unable to download results"):
      log.error("Unable to download results")
      sys.exit(1)
    elif content.count("Error when trying to retrieve support script output"):
      log.error("Error when trying to retrieve support script output")
      sys.exit(1)

    out_fd.write(content)

###############################################################################
# MAIN
###############################################################################

if __name__ == "__main__":
  log.setLevel(DEFAULTLOGLEVEL)
  logStreamHandler = logging.StreamHandler(sys.stdout)
  logStreamHandler.setFormatter(logging.Formatter("%(asctime)s %(levelname)5s %(name)s %(lineno)d: %(message)s"))
  log.addHandler(logStreamHandler)

  # Get command options
  parser = OptionParser()

  parser.add_option("-f", "--input-file", dest="inputFile",
                      help="Input XML file", metavar="FILE")

  parser.add_option("-o", "--output", dest="outputFile",
          help="Output file name", metavar="FILE")

  parser.add_option("-g", "--sign-password", dest="signpassword",
          help="Sign password for signing/import/export")

  parser.add_option("-t", "--timeout", dest="timeout",
          help="Timeout value (for Authz cache and support script)")

  parser.add_option("--max-hostload", dest="maxhostload",
          help="Value for max number of concurrent authz requests per server")

  parser.add_option("--sources", dest="sources",
                    help="List of databases to sync (database1,database2,database3)")

  parser.add_option("--frontend", dest="frontend",
                    help="Frontend used to export keymatches or related queries")

  parser.add_option("--collection", dest="collection",
                    help="Collection name")

  # actionsOptions
  actionOptionsGrp = OptionGroup(parser, "Actions:")

  actionOptionsGrp.add_option("-i", "--import", dest="actimport",
          help="Import config file to GSA", action="store_true")

  actionOptionsGrp.add_option("-e", "--export", dest="export",
          help="Export GSA config file from GSA", action="store_true")

  actionOptionsGrp.add_option("-s", "--sign", dest="sign", action="store_true",
           help="Sign input XML file")

  actionOptionsGrp.add_option("-r", "--verify", dest="verify", action="store_true",
           help="Verify signature/HMAC in XML Config")

  actionOptionsGrp.add_option("-a", "--set", dest="setaccesscontrol", action="store_true",
           help="Set Access Control settings")

  actionOptionsGrp.add_option("-l", "--all_urls", dest="all_urls",
          help="Export all URLs from GSA using Crawl Diagnostics", action="store_true")

  actionOptionsGrp.add_option("-L", "--export_all_urls", dest="export_all_urls",
                              help="Export All URLs using Export URLs", action="store_true")

  actionOptionsGrp.add_option("-d" ,"--database_sync", dest="database_sync",
                              help="Sync databases", action="store_true")

  actionOptionsGrp.add_option("-k" ,"--keymatches_export", dest="keymatches_export",
                              help="Export All Keymatches", action="store_true")

  actionOptionsGrp.add_option("-y" ,"--synonyms_export", dest="synonyms_export",
                              help="Export All Related Queries", action="store_true")

  actionOptionsGrp.add_option("-z", "--get-status", dest="getstatus",
                              action="store_true", help="Get GSA Status")

  actionOptionsGrp.add_option("-c", "--get-collection-report", dest="getcollection",
                              action="store_true", help="Get GSA Collection Statistics")

  actionOptionsGrp.add_option("-m", "--custom-sscript", dest="cus_sscript",
                              action="store_true", help="Run custom support script")

  parser.add_option_group(actionOptionsGrp)

  # gsaHostOptions
  gsaHostOptions = OptionGroup(parser, "GSA info")

  gsaHostOptions.add_option("-n", "--hostname", dest="gsaHostName",
          help="GSA hostname")

  gsaHostOptions.add_option("--port", dest="port",
          help="Upload port. Defaults to 8000", default="8000")

  gsaHostOptions.add_option("-u", "--username", dest="gsaUsername",
            help="Username to login GSA")

  gsaHostOptions.add_option("-p", "--password", dest="gsaPassword",
            help="Password for GSA user")

  parser.add_option_group(gsaHostOptions)

  parser.add_option("-v", "--verbose", action="count", dest="verbosity", help="Specify multiple times to increase verbosity")

  (options, args) = parser.parse_args()

  if options.verbosity:
    # The -v option is counted so more -v the more verbose we should be.
    # As the log level are actually ints of multiples of 10
    # we count how many -v were specified x 10 and subtract the result from the minimum level of logging
    startingLevel = DEFAULTLOGLEVEL
    logOffset = 10 * options.verbosity
    logLevel = startingLevel - logOffset
    log.setLevel(logLevel)

  # Actions actimport, export, sign, & verify need signpassword
  # if not options.setaccesscontrol:
  if options.actimport or options.export or options.sign or options.verify:
    # Verify opts
    if not options.signpassword:
      log.error("Signing password not given")
      sys.exit(3)

    if len(options.signpassword) < 8:
      log.error("Signing password must be 8 characters or longer")
      sys.exit(3)

  if options.timeout:
    try:
      timeout = int(options.timeout)
      log.info("Value of timeout: %d" % (timeout))
    except ValueError:
      log.error("Timeout is not an integer: %s" % (timeout))
      sys.exit(3)

  action = None

  # Ensure only one action is specified
  if options.actimport:
    action = "import"
  if options.setaccesscontrol:
    if action:
      log.error("Specify only one action")
      sys.exit(3)
    else:
      action = "setaccesscontrol"
  if options.export:
    if action:
      log.error("Specify only one action")
      sys.exit(3)
    else:
      action = "export"
  if options.sign:
    if action:
      log.error("Specify only one action")
      sys.exit(3)
    else:
      action = "sign"
  if options.verify:
    if action:
      log.error("Specify only one action")
      sys.exit(3)
    else:
      action = "verify"
  if options.all_urls:
    if action:
      log.error("Specify only one action")
      sys.exit(3)
    else:
      action = "all_urls"
  if options.export_all_urls:
    if action:
      log.error("Specify only one action")
      sys.exit(3)
    else:
      action="export_all_urls"
  if options.database_sync:
    if action:
      log.error("Specify only one action")
      sys.exit(3)
    else:
      action = "database_sync"
  if options.keymatches_export:
    if action:
      log.error("Specify only one action")
      sys.exit(3)
    else:
      action = "keymatches_export"
  if options.synonyms_export:
    if action:
      log.error("Specify only one action")
      sys.exit(3)
    else:
      action = "synonyms_export"
  if options.getstatus:
    if action:
      log.error("Specify only one action")
      sys.exit(3)
    else:
      action = "status"
  if options.getcollection:
    if action:
      log.error("Specify only one action")
      sys.exit(3)
    else:
      action = "getcollection"
  if options.cus_sscript:
    if action:
      log.error("Specify only one action")
      sys.exit(3)
    else:
      action = "cus_sscript"
  if not action:
      log.error("No action specified")
      sys.exit(3)


  if action != "sign" or action != "verify":
    #Check user, password, host
    if not options.gsaHostName:
      log.error("hostname not given")
      sys.exit(3)
    if not options.gsaUsername:
      log.error("username not given")
      sys.exit(3)
    if not options.gsaPassword:
      log.error("password not given")
      sys.exit(3)

  # Actions
  if action == "sign":
    if not options.inputFile:
      log.error("Input file not given")
      sys.exit(3)

    if not options.outputFile:
      log.error("Output file not given")
      sys.exit(3)

    log.info("Signing %s" % options.inputFile)
    gsac = gsaConfig(options.inputFile)
    gsac.sign(options.signpassword)
    log.info("Writing signed file to %s" % options.outputFile)
    gsac.writeFile(options.outputFile)

  elif action == "import":
    if not options.inputFile:
      log.error("Input file not given")
      sys.exit(3)
    log.info("Importing %s to %s" % (options.inputFile, options.gsaHostName) )
    gsac = gsaConfig(options.inputFile)
    if not gsac.verifySignature(options.signpassword):
      log.warn("Pre-import validation failed. Signature does not match. Expect the GSA to fail on import")
    gsaWI = gsaWebInterface(options.gsaHostName, options.gsaUsername, options.gsaPassword)
    gsaWI.importConfig(gsac, options.signpassword)
    log.info("Import completed")

  elif action == "export":
    if not options.outputFile:
      log.error("Output file not given")
      sys.exit(3)
    log.info("Exporting config from %s to %s" % (options.gsaHostName, options.outputFile) )
    gsaWI = gsaWebInterface(options.gsaHostName, options.gsaUsername, options.gsaPassword)
    gsac = gsaWI.exportConfig(options.signpassword)
    gsac.writeFile(options.outputFile)
    log.info("Export completed")

  elif action == "verify":
    if not options.inputFile:
      log.error("Input file not given")
      sys.exit(3)
    gsac = gsaConfig(options.inputFile)
    if gsac.verifySignature(options.signpassword):
      log.info("XML Signature/HMAC matches supplied password" )
    else:
      log.warn("XML Signature/HMAC does NOT match supplied password" )
      sys.exit(1)

  elif action == "setaccesscontrol":
    log.info("Setting access control")
    if options.maxhostload:
      try:
        maxhostload = int(options.maxhostload)
        log.info("Value of max hostload: %d" % (maxhostload))
      except ValueError:
        log.error("Max hostload is not an integer: %s" % (maxhostload))
        sys.exit(3)

    if options.maxhostload and options.timeout:
      gsaWI = gsaWebInterface(options.gsaHostName, options.gsaUsername, options.gsaPassword)
      gsaWI.setAccessControl(options.maxhostload, options.timeout)
    elif options.maxhostload:
      gsaWI = gsaWebInterface(options.gsaHostName, options.gsaUsername, options.gsaPassword)
      gsaWI.setAccessControl(options.maxhostload)
    else:
      log.error("No value for Authorization Cache Timeout or Max Host Load")
      sys.exit(3)

  elif action == "all_urls":
    if not options.outputFile:
      log.error("Output file not given")
      sys.exit(3)
    try:
      f = open(options.outputFile, 'w')
    except IOError:
      log.error("unable to open %s to write" % options.outputFile)
      sys.exit(3)
    else:
      log.info("Retrieving URLs in crawl diagnostics to %s" % options.outputFile)
      gsaWI = gsaWebInterface(options.gsaHostName, options.gsaUsername, options.gsaPassword)
      gsaWI.getAllUrls(f)
      f.close()
      log.info("All URLs exported.")

  elif action == "export_all_urls":
    if not options.outputFile:
      log.error("Output file not given")
      sys.exit(3)
    try:
      f = open(options.outputFile, 'w')
    except IOError:
      log.error("unable to open %s to write" % options.outputFile)
      sys.exit(3)

    log.info("Exporting all URLs to %s" % options.outputFile)
    gsaWI = gsaWebInterface(options.gsaHostName, options.gsaUsername, options.gsaPassword)
    gsaWI.exportAllUrls(f)
    f.close()

  elif action == "database_sync":
    if not options.sources:
      log.error("No sources to sync")
      sys.exit(3)
    databases = options.sources.split(",")
    log.info("Sync'ing databases %s" % options.sources)
    gsaWI = gsaWebInterface(options.gsaHostName, options.gsaUsername, options.gsaPassword)
    gsac = gsaWI.syncDatabases(databases)
    log.info("Sync completed")

  elif action == "keymatches_export":
    if not options.outputFile:
      log.error("Output file not given")
      sys.exit(3)
    if not options.frontend:
      log.error("No frontend defined")
      sys.exit(3)
    try:
      f = open(options.outputFile, 'w')
    except IOError:
      log.error("unable to open %s to write" % options.outputFile)
      sys.exit(3)

    log.info("Exporting keymatches for %s to %s" % (options.frontend, options.outputFile) )
    gsaWI = gsaWebInterface(options.gsaHostName, options.gsaUsername, options.gsaPassword)
    gsaWI.exportKeymatches(options.frontend, f)
    f.close()

  elif action == "synonyms_export":
    if not options.outputFile:
      log.error("Output file not given")
      sys.exit(3)
    if not options.frontend:
      log.error("No frontend defined")
      sys.exit(3)
    try:
      f = open(options.outputFile, 'w')
    except IOError:
      log.error("unable to open %s to write" % options.outputFile)
      sys.exit(3)

    log.info("Exporting synonyms for %s to %s" % (options.frontend, options.outputFile) )
    gsaWI = gsaWebInterface(options.gsaHostName, options.gsaUsername, options.gsaPassword)
    gsaWI.exportSynonyms(options.frontend, f)
    f.close()
  elif action == "status":
    gsaWI = gsaWebInterface(options.gsaHostName, options.gsaUsername, options.gsaPassword)
    gsaWI.getStatus()
  elif action == "getcollection":
    if not options.collection:
      collection = "default_collection"
    else:
      collection = options.collection
    gsaWI = gsaWebInterface(options.gsaHostName, options.gsaUsername, options.gsaPassword)
    gsaWI.getCollection(collection)
  elif action == "cus_sscript":
    if not options.inputFile:
      log.error("Input file not given")
      sys.exit(3)
    if not options.outputFile:
      log.error("Output file not given")
      sys.exit(3)
    try:
      f = open(options.outputFile, 'w')
    except IOError:
      log.error("unable to open %s to write" % options.outputFile)
      sys.exit(3)

    gsaWI = gsaWebInterface(options.gsaHostName, options.gsaUsername, options.gsaPassword)
    if options.timeout:
      gsaWI.runCusSscript(options.inputFile, f, timeout)
    else:
      gsaWI.runCusSscript(options.inputFile, f)
