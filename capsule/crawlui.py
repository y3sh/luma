# Copyright 2016 The Vanadium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.
"""A module for installing and crawling the UI of Android application."""

import copy
import json
import os
import re
import subprocess
import time

from com.dtmilano.android.common import obtainAdbPath
from view import View

MAX_HEIGHT = 0
MAX_WIDTH = 0
NAVBAR_HEIGHT = 0

# Visibility
VISIBLE = 0x0
INVISIBLE = 0x4
GONE = 0x8

ADB_PATH = obtainAdbPath()
BACK_BUTTON = 'back button'
# Return a unique string if the package is not the focused window. Since
# activities cannot have spaces, we ensure that no activity will be named this.
EXITED_APP = 'exited app'

# How many times we should try pressing the back button to return to the app
# before giving up.
NUM_BACK_PRESSES = 3


def extract_between(text, sub1, sub2, nth=1):
  """Extracts a substring from text between two given substrings."""
  # Credit to
  # https://www.daniweb.com/programming/software-development/code/446964/extract-a-string-between-2-substrings-python-

  # Prevent sub2 from being ignored if it's not there.
  if sub2 not in text.split(sub1, nth)[-1]:
    return None
  return text.split(sub1, nth)[-1].split(sub2, nth)[0]


def set_device_dimens(vc, device):
  """Sets global variables to the dimensions of the device."""
  global MAX_HEIGHT, MAX_WIDTH, NAVBAR_HEIGHT
  vc_dump = vc.dump(window='-1')
  # Returns a string similar to "Physical size: 1440x2560"
  size = device.shell('wm size')
  MAX_HEIGHT = int(extract_between(size, 'x', '\r'))
  MAX_WIDTH = int(extract_between(size, ': ', 'x'))
  NAVBAR_HEIGHT = (
      vc_dump[0].getY() - int(vc_dump[0]['layout:getLocationOnScreen_y()']))


def perform_press_back(device):
  device.press('KEYCODE_BACK')


def return_to_app_activity(package_name, device):
  """Tries to press back a number of times to return to the app."""

  # Returns the name of the activity, or EXITED_APP if it could not return.
  for press_num in range(0, NUM_BACK_PRESSES):
    perform_press_back(device)
    activity = obtain_activity_name(package_name, device)
    if activity != EXITED_APP:
      print 'Returned to app'
      return activity

    time.sleep(5)
    print 'Failed returning to app, attempt #' + str(press_num + 1)

  return EXITED_APP


def obtain_activity_name(package_name, device):
  """Gets the current running activity of the package."""
  # TODO(afergan): See if we can consolidate this with obtain_fragment_list, but
  # still make sure that the current app has focus.
  # TODO(afergan): Check for Windows compatibility.
  activity_str = device.shell('dumpsys window windows '
                              '| grep -E \'mCurrentFocus\'')

  # If a popup menu has captured the focus, the focus will be in the format
  # mCurrentFocus=Window{8f1328e u0 PopupWindow:53a5957}
  if 'PopupWindow' in activity_str:
    popup_str = extract_between(activity_str, 'PopupWindow', '}')
    return 'PopupWindow' + popup_str.replace(':', '')

  if package_name in activity_str:
    # The current focus returns a string in the format
    # mCurrentFocus=Window{35f66c3 u0 com.google.zagat/com.google.android.apps.
    # zagat.activities.BrowseListsActivity}
    # We only want the text between the final period and the closing bracket.
    return extract_between(activity_str, '.', '}', -1)

  return EXITED_APP


def obtain_frag_list(package_name, device):
  """Gets the list of fragments in the current view."""
  activity_dump = device.shell('dumpsys activity ' + package_name)
  frag_dump = re.findall('Added Fragments:(.*?)FragmentManager', activity_dump,
                         re.DOTALL)
  if frag_dump:
    frag_list = re.findall(': (.*?){', frag_dump[0], re.DOTALL)
    return frag_list

  return 'NoFrag'


def obtain_package_name(device):
  """Gets the package name of the current focused window."""
  activity_str = device.shell('dumpsys window windows '
                              '| grep -E \'mCurrentFocus\'')

  # The current focus returns a string in the format
  # mCurrentFocus=Window{35f66c3 u0 com.google.zagat/com.google.android.apps.
  # zagat.activities.BrowseListsActivity}
  # We want the text before the backslash
  pkg_name = extract_between(activity_str, ' ', '/', -1)
  print 'Package name is ' + pkg_name
  return pkg_name


def save_view_data(package_name, activity, frag_list, vc_dump):
  """Stores the view hierarchy and screenshots with unique filenames."""
  # Returns the path to the screenshot and the file number.

  first_frag = frag_list[0]
  directory = (
      os.path.dirname(os.path.abspath(__file__)) + '/data/' + package_name)
  if not os.path.exists(directory):
    os.makedirs(directory)
  file_num = 0
  dump_file = os.path.join(
      directory, activity + '-' + first_frag + '-' + str(file_num) + '.json')
  while os.path.exists(dump_file):
    file_num += 1
    dump_file = os.path.join(
        directory,
        activity + '-' + first_frag + '-' + str(file_num) + '.json')

  view_info = {}
  view_info['hierarchy'] = {}
  view_info['fragmentList'] = frag_list

  for component in vc_dump:
    # Because the children and parent are each instances, they are not JSON
    # serializable. We replace them with just the ids of the instances (and
    # discard the device info).
    dict_copy = copy.copy(component.__dict__)
    del dict_copy['device']
    if dict_copy['parent']:
      dict_copy['parent'] = dict_copy['parent'].getUniqueId()
    dict_copy['children'] = []
    for child in component.__dict__['children']:
      dict_copy['children'].append(child.getUniqueId())
    view_info['hierarchy'][component.getUniqueId()] = dict_copy

  with open(dump_file, 'w') as out_file:
    json.dump(view_info, out_file, indent=2)

  screen_name = activity + '-' + first_frag + '-' + str(file_num) + '.png'
  screen_path = os.path.join(directory, screen_name)
  # device.shell() does not work for taking/pulling screencaps.
  subprocess.call([ADB_PATH, 'shell', 'screencap', '/sdcard/' + screen_name])
  subprocess.call([ADB_PATH, 'pull', '/sdcard/' + screen_name, screen_path])
  # Returns the filename & num so that the screenshot can be accessed
  # programatically.
  return [screen_path, file_num]


def save_ui_flow_relationships(view_to_save, package_name):
  """Dumps to file the click dictionary and preceding Views."""
  directory = (
      os.path.dirname(os.path.abspath(__file__)) + '/data/' + package_name)
  click_file = os.path.join(directory, view_to_save.get_name() + '-clicks.json')
  click_info = {}
  click_info['click_dict'] = view_to_save.click_dict
  click_info['preceding'] = view_to_save.preceding
  with open(click_file, 'w') as out_file:
    json.dump(click_info, out_file, indent=2)


def find_view_idx(activity, frag_list, vc_dump, view_array):
  """Finds the index of the current View in the view array (-1 if new View)."""
  for i in range(len(view_array)):
    if view_array[i].is_duplicate(activity, frag_list, vc_dump):
      return i
  return -1


def create_view(package_name, vc_dump, activity, frag_list):
  """Stores the current view in the View data structure."""
  screenshot_info = save_view_data(package_name, activity, frag_list, vc_dump)
  v = View(activity, frag_list, vc_dump, screenshot_info[0], screenshot_info[1])

  for component in v.hierarchy:
    # TODO(afergan): For now, only click on certain components, and allow custom
    # components. Evaluate later if this is worth it or if we should just click
    # on everything attributed as clickable.
    if (component.isClickable() and component.getVisibility() == VISIBLE and
        component.getX() >= 0 and component.getX() <= MAX_WIDTH and
        component.getWidth() > 0 and
        component.getY() >= NAVBAR_HEIGHT and component.getY() <= MAX_HEIGHT and
        component.getHeight() > 0):
      print (component.getId() + ' ' + component.getClass()
             + ' ' + str(component.getXY()) + '-- will be clicked')
      v.clickable.append(component)

  return v


def link_ui_views(last_view, curr_view, last_clicked, package_name,
                  view_array):
  """Stores the relationship between last_view and curr_view."""

  # We store in the View information that the last view links to the current
  # view, and that the current view can be reached from the last view. We use
  # the id of the last clicked element as the dictionary key so that we know
  # which element leads from view to view.

  if last_clicked:
    print 'Last clicked: ' + last_clicked
    last_view.click_dict[last_clicked] = curr_view.get_name()
    curr_view.preceding.append(last_view.get_name())
  else:
    print 'Lost track of last clicked!'
  view_array.append(curr_view)
  # TODO(afergan): Remove this later. For debugging, we print the clicks after
  # each click to a new view is recorded. However, this results in a lot of
  # repeated writes to the same file. In the future, we can just write each
  # file once we're done crawling the app.
  save_ui_flow_relationships(last_view, package_name)
  save_ui_flow_relationships(curr_view, package_name)


def obtain_curr_view(activity, package_name, vc_dump, view_array, device):
  """Extracts UI info and return the current View."""

  # Gets the current UI info. If we have seen this UI before, return the
  # existing View. If not, create a new View and save it to the view array.

  frag_list = obtain_frag_list(package_name, device)
  view_idx = find_view_idx(activity, frag_list, vc_dump, view_array)

  if view_idx >= 0:
    print 'Found duplicate'
    return view_array[view_idx]
  else:
    print 'New view'
    new_view = create_view(package_name, vc_dump, activity, frag_list)
    view_array.append(new_view)
    return new_view


def crawl_package(vc, device, debug, package_name=None):
  """Main crawler loop. Evaluates views, store new views, and click on items."""
  set_device_dimens(vc, device)
  view_array = []

  last_clicked = ''
  if debug or not package_name:  # These should be equal
    package_name = obtain_package_name(device)

  # Store the root View
  print 'Storing root'
  vc_dump = vc.dump(window='-1')
  activity = obtain_activity_name(package_name, device)
  view_root = obtain_curr_view(activity, package_name, vc_dump, view_array,
                               device)
  curr_view = view_root

  while True:

    # If last click opened the keyboard, assume we're in the same view and just
    # click on the next element. Since opening the keyboard can leave traces of
    # additional components, don't check if view is duplicate.
    # TODO(afergan): Is this a safe assumption?
    if device.isKeyboardShown():
      perform_press_back(device)

    activity = obtain_activity_name(package_name, device)

    if activity is EXITED_APP:
      activity = return_to_app_activity(package_name, device)
      if activity is EXITED_APP:
        print 'Current view is not app and we cannot return'
        break
      else:
        last_clicked = BACK_BUTTON

    last_view = curr_view
    vc_dump = vc.dump(window='-1')
    curr_view = obtain_curr_view(activity, package_name, vc_dump, view_array,
                                 device)
    print 'Curr view: ' + curr_view.get_name()
    if not last_view.is_duplicate_view(curr_view):
      print 'At a diff view!'
      link_ui_views(last_view, curr_view, last_clicked, package_name,
                    view_array)

    print 'Num clickable: ' + str(len(curr_view.clickable))

    if curr_view.clickable:
      c = curr_view.clickable[-1]
      print('Clicking {} {}, ({},{})'.format(c.getUniqueId(), c.getClass(),
                                             c.getX(), c.getY()))
      c.touch()
      last_clicked = c.getUniqueId()
      del curr_view.clickable[-1]

    else:
      print 'Clicking back button'
      perform_press_back(device)
      last_view = curr_view
      last_clicked = BACK_BUTTON
      activity = obtain_activity_name(package_name, device)

      if activity is EXITED_APP:
        activity = return_to_app_activity(package_name, device)
        if activity is EXITED_APP:
          print 'Clicking back took us out of the app'
          break

      # Make sure we have changed views.
      vc_dump = vc.dump(window='-1')
      curr_view = obtain_curr_view(activity, package_name, vc_dump,
                                   view_array, device)
      if last_view.is_duplicate_view(curr_view):
        # We have nothing left to click, and the back button doesn't change
        # views.
        print 'Pressing back keeps at the current view'
        break
      else:
        link_ui_views(last_view, curr_view, 'back button', package_name,
                      view_array)