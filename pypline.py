
# https://github.com/packagecontrol/requests
# https://stackoverflow.com/questions/38137760/jenkins-rest-api-create-job

import os
import sys
import pprint
import requests
import tempfile
import subprocess
import ntpath

from xml import etree
from time import sleep
from xml.sax.saxutils import escape

import sublime
import sublime_plugin
import requests
import json

class PyplineCommand(sublime_plugin.TextCommand):

  settings =              None
  jenkins_uri =           ""
  username =              ""
  api_token =             ""
  job_prefix =            ""
  open_browser =          True
  timeout_secs =          10
  display_build_output =  False
  auth_tuple =            None
  auth_crumb =            None
  output_panel =          None

  edit = None

  def run(self, edit, target_idx = -1):
    self.settings =       sublime.load_settings("pypline.sublime-settings")
    self.jenkins_uri =    self.settings.get("jenkins_uri", "http://127.0.0.1:8080")
    self.username =       self.settings.get("username", None)
    self.api_token =      self.settings.get("password", None)
    self.job_prefix =     self.settings.get("job_prefix", "temp")
    self.open_browser =   self.settings.get("open_browser", True)
    self.timeout_secs =    self.settings.get("open_browser_timeout_secs", 10)
    self.display_build_output = self.settings.get("display_build_output", False)
    self.auth_tuple =   (self.username, self.api_token)

    # Determine target.
    if target_idx != -1:
      self.option_select(target_idx, edit)
    else:      
      self.view.window().show_quick_panel([
        "Execute Pipeline", 
        "Show Pipeline Api"
      ], lambda idx: self.option_select(idx, edit))

  # Starts the flow for remotely building a Jenkins pipeline job,
  # using the user's view contents as the pipeline script.
  #
  def start_pipeline_build(self, edit):

    # Create/retrieve/show our output panel and clear the contents.
    self.output_panel = sublime.active_window().create_output_panel("pipeline_out")
    self.output_panel.run_command("select_all")
    self.output_panel.run_command("right_delete")
    self.output_panel.set_read_only(False)
    self.output_panel.set_syntax_file("Packages/Text/Plain Text.tmLanguage")
    sublime.active_window().run_command("show_panel", {"panel": "output.pipeline_out"})

    # html = self.get_api_html()
    # self.OUT(html)
    # self.view.show_popup(html)

    # Retrieve jenkins authentication crumb (CSRF token) to make requests remotely.
    # TODO: CSRF crumb support for console output is not supported yet.
    self.get_auth_crumb()

    filename = filename = os.path.splitext(ntpath.basename(self.view.file_name()))[0]
    content = self.view.substr(sublime.Region(0, self.view.size()))
    self.build_pipeline(content, filename)

  #############################################################################
  # Selection
  #############################################################################    

  def option_select(self, index, edit):

    if index == -1: return
    if index == 0:
      sublime.set_timeout_async(lambda: self.start_pipeline_build(edit), 0)
    if index == 1:
      self.open_browser_at("{}/pipeline-syntax".format(self.jenkins_uri))

    return

  #############################################################################
  # Logging
  #############################################################################

  def OUT(self, message):
    self.output_panel.run_command("append", {"characters": "{}\n".format(message), "scroll_to_end": True})
    # self.output_panel.add_regions("ham", [self.output_panel.visible_region()], "string", "", 0)

  def MYPRINT(self, label, message):
    print("[{}] - {}".format(label, message))
    self.OUT("[{}] - {}".format(label, message))
    
  def INFO(self, message):
    self.MYPRINT("INFO", message)

  def WARNING(self, message):
    self.MYPRINT("WARNING", message)

  def ERROR(self, message):
    self.MYPRINT("ERROR", message)

  #############################################################################
  # Request Methods
  #############################################################################

  def get_headers(self):
    if not self.auth_crumb:
      return {'Content-Type':'text/xml'}
    return {'Content-Type':'text/xml', self.auth_crumb[0]:self.auth_crumb[1]}

  def get_auth_crumb(self):
    url = "http://{}:{}@{}//crumbIssuer/api/json".format(
      self.username,
      self.api_token,
      self.jenkins_uri.replace("http://", ""))

    self.INFO("GET: {}".format(url))     
    r = requests.get(url)      
    if r.status_code != requests.codes.ok:
      self.WARNING("GET: {} - Could not retrieve 'crumb' for authentication - Status code {}".format(
      url,  r.status_code))
      return None
    
    data = json.loads(r.text)
    self.auth_crumb = (data["crumbRequestField"], data["crumb"])
    self.INFO("Crumb retrieved - {}:{}".format(self.auth_crumb[0], self.auth_crumb[1]))

  def get_api_html(self):
    r = requests.get("http://127.0.0.1:8080/pipeline-syntax/", auth=self.auth_tuple)
    return r.text

  def open_browser_at(self, url):
    if sys.platform=='win32':
      os.startfile(url)
    elif sys.platform=='darwin':
      subprocess.Popen(['open', url])
    else:
      try:
        subprocess.Popen(['xdg-open', url])
      except:
        self.INFO('Please open a browser on: ' + url)

  def job_exists(self, jobname):
    url = "{}/job/{}".format(self.jenkins_uri, jobname)
    self.INFO("GET: {}".format(url))
    r = requests.get(url, auth=self.auth_tuple)
    if r.status_code == requests.codes.ok:
      return True 
    return False

  def get_job_config(self, jobname):
    url = "{}/job/{}/config.xml".format(self.jenkins_uri, jobname)
    self.INFO("GET: {}".format(url))
    r = requests.get(url, auth=self.auth_tuple)
    if r.status_code == requests.codes.ok:
      return r.text
    self.ERROR("GET: {} - Status Code: {}".format(url, r.status_code))
    return None

  def update_job(self, jobname, content):
    url = "{}/job/{}/config.xml".format(self.jenkins_uri, jobname)

    self.INFO("POST: {}".format(url)) 
    r = requests.post(
      url, 
      data = content,
      headers=self.get_headers(),
      auth=self.auth_tuple)

    if r.status_code == requests.codes.ok:
      return r.text + "."
    self.ERROR("POST: {} - Could not update job {} - Status code {}".format(
      url, jobname, r.status_code))
    return None
    
  def create_job(self, jobname, content):
    url = "{}/createItem?name={}".format(self.jenkins_uri, jobname)

    self.INFO("POST: {}".format(url))     
    r = requests.post(
      url, 
      data = content,
      headers=self.get_headers(),
      auth=self.auth_tuple)

    if r.status_code == requests.codes.ok:
      return r.text + "."
    self.ERROR("POST: {} - Could not create job {} - Status code {} - {}".format(
      url, jobname, r.status_code, r.text))
    return None

  def next_buildnum(self, jobname):
    url = "{}/job/{}/lastBuild/buildNumber".format(self.jenkins_uri, jobname)

    self.INFO("GET: {}".format(url))
    r = requests.get(
      url,
      headers=self.get_headers())    

    if r.status_code != requests.codes.ok:
      self.WARNING("GET: {} - Issue retrieving build number for job {} - Status code: {} - {}".format(
        url, jobname, r.status_code, r.text))
      self.WARNING("Defaulting build number to 1.")
      return 1
    return int(r.text) + 1

  def build_job(self, jobname):
    url = "{}/job/{}/build".format(self.jenkins_uri, jobname)

    self.INFO("POST: {}".format(url))
    r = requests.post(
      url, 
      auth=self.auth_tuple,
      headers=self.get_headers())

    if r.status_code == requests.codes.ok or r.status_code == 201:
      return r.text + "."
    self.ERROR("POST: {} - Could not build job {} - Status code {}".format(
      url, jobname, r.status_code))
    return None

  def build_ready(self, build_url):
    timeout = self.timeout_secs
    while timeout > 0:
      r = requests.get(build_url)
      if r.status_code == requests.codes.ok:
        return True
      self.INFO("Build not ready. Waiting...")
      sleep(1)
      timeout = timeout - 1

    self.ERROR("Timed out at {} secs waiting for build at {}".format(self.timeout_secs, build_url))    
    return False

  # Remotely builds the passed Jenkins Pipeline source.
  # Pipeline source is inserted into a template 'config.xml' and then
  # remotely determines whether job exists and needs to be updated,
  # or job doesn't exist and needs to be created.
  # 
  def build_pipeline(self, source, job): 
    content = ""
    xmlpath = os.path.join(sublime.packages_path(), "pypline")
    with open('{}/config.xml'.format(xmlpath), 'r') as myfile:
      content = myfile.read().replace('\n', '')
    config = content.replace("++CONTENT++", source)

    # If job exists, update. If not, create.
    jobname = "{}-{}".format(self.job_prefix, job) 

    next_build_number = 1
    if not self.job_exists(jobname):
      self.INFO("{} doesn't exist. Creating...".format(jobname))
      if not self.create_job(jobname, config): return
    else:
      self.INFO("{} already exists. Reconfiguring...".format(jobname))
      uj = self.update_job(jobname, config)
      if not uj:
        self.INFO(uj)
        return
      next_build_number = self.next_buildnum(jobname)

    # Start build, create build URL, and wait for build to begin.
    if not self.build_job(jobname): return
    build_url = "{}/job/{}/{}".format(self.jenkins_uri, jobname, next_build_number)
    self.INFO("Build started for '{}' at {}".format(jobname, build_url))

    # Wait for build to start then open browser to the URL (if specified)    
    if not self.build_ready(build_url): return
    if self.open_browser:
      self.INFO("Build ready! Opening browser to console output.")
      self.open_browser_at(build_url)

    # Print build output to console if specified.
    if self.display_build_output:
      self.INFO("Display build output enabled.")
      self.console_output(jobname, next_build_number)

  def highlight_output(self):
    self.output_panel.add_regions("", [sublime.Region(0, self.output_panel.size())], "string", "", 0)

  def console_output(self, jobname, buildnumber):
    # Get job console till job stops
    job_url = self.jenkins_uri + "/job/" + jobname + "/" + str(buildnumber) + "/logText/progressiveText"
    self.INFO("-------------------------------------------------------------------------------")
    self.INFO("Getting Console output {}".format(job_url))
    self.INFO("-------------------------------------------------------------------------------\n")
    start_at = 0
    stream_open = True
    check_job_status = 0

    console_requests = requests.session()
    
    while stream_open:

      console_response = console_requests.post(
        job_url,
        data={'start': start_at })

      content_length = int(console_response.headers.get("Content-Length",-1))

      if console_response.status_code != 200:
        self.ERROR("Error getting console output. Status code: {}".format(console_response.status_code))
        self.ERROR(console_response.content)
        self.ERROR(console_response.headers)
        return

      if content_length == 0:
        sleep(1)
        check_job_status +=1
      else:
        check_job_status = 0

        # Print to output panel.
        content = str(console_response.content, 'ascii')
        for line in content.replace("\\t", "\t").split("\r\n"):
          self.OUT("{}".format(line))

        sleep(1)

        start_at = int(console_response.headers.get("X-Text-Size"))

      # No content for a while lets check if job is still running
      if check_job_status > 1:

        job_status_url = self.jenkins_uri + "/job/" + jobname + "/" + str(buildnumber) + "/api/json"
        job_requests = requests.get(
          job_status_url,
          headers=self.get_headers())

        job_bulding= job_requests.json().get("building")
        if not job_bulding:
          # We are done
          self.INFO("Console stream ended.")
          stream_open = False
        else:
          # Job is still running
          check_job_status = 0
  
    self.complete = True
    self.INFO("-------------------------------------------------------------------------------")