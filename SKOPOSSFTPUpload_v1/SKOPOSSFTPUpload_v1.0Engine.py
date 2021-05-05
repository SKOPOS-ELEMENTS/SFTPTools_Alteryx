"""
AyxPlugin (required) has-a IncomingInterface (optional).
Although defining IncomingInterface is optional, the interface methods are needed if an upstream tool exists.
"""

import re
import io
import os
import AlteryxPythonSDK as Sdk
import xml.etree.ElementTree as Et
import pysftp
import base64
from datetime import datetime
from enum import Enum

REGEX_HOSTNAME = r"^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$"

class AyxPlugin:
    """
    Implements the plugin interface methods, to be utilized by the Alteryx engine to communicate with a plugin.
    Prefixed with "pi", the Alteryx engine will expect the below five interface methods to be defined.
    """

    class UploadMode(Enum):
        NONE_MODE = 0
        UPLOAD_FILES = 1
        UPLOAD_BLOBS = 2

    class FileHandling(Enum):
        NONE_HANDLING = 0
        KEEP_FILES = 1
        DELETE_FILES = 2
        MOVE_FILES = 3
    
    def __init__(self, n_tool_id: int, alteryx_engine: object, output_anchor_mgr: object):
        """
        Constructor is called whenever the Alteryx engine wants to instantiate an instance of this plugin.
        :param n_tool_id: The assigned unique identification for a tool instance.
        :param alteryx_engine: Provides an interface into the Alteryx engine.
        :param output_anchor_mgr: A helper that wraps the outgoing connections for a plugin.
        """
        
        # Default properties
        self.n_tool_id = n_tool_id
        self.alteryx_engine = alteryx_engine
        self.output_anchor_mgr = output_anchor_mgr

        # SFTP settings
        self.sftp_settings = dict({
            'hostname': None,
            'port': '22',
            'username': None,
            'password': None,
            'key_filepath': None,
            'key_passphrase': None,
            'remote_path': '/'
        })
        # Tool mode: What should we do?
        self.upload_mode = self.UploadMode.NONE_MODE
        self.file_handling = self.FileHandling.NONE_HANDLING
        self.move_path = None
        self.incoming_field = None
        self.blob_field = None
        self.overwrite = False

        # Storage
        self.input_anchor = None
        self.input_recordinfo = None

    def validate_settings(self, silent=False) -> bool:
        """Validate settings
        Checks whether the settings made in the GUI are valid and provides error messages otherwise.
        
        :return: Status of validation
        :rtype: bool
        """
        validation_result = True
        # Validate the settings
        if not self.sftp_settings['hostname']:
            if not silent:
                self.output_message('Please enter a hostname.')
            validation_result = False
        elif not re.match(REGEX_HOSTNAME, self.sftp_settings['hostname']):
            if not silent:
                self.output_message('Please enter a valid hostname without protocol, user or port.')
            validation_result = False

        if not self.sftp_settings['port']:
            if not silent:
                self.output_message('Please provide a port for the connection.')
            validation_result = False

        if not self.sftp_settings['username']:
            if not silent:
                self.output_message('Please provide a username for the connection.')
            validation_result = False

        if not self.sftp_settings['remote_path']:
            if not silent:
                self.output_message('Please provide a remote path. Root directory would be /.')
            validation_result = False

        if self.upload_mode == self.UploadMode.NONE_MODE:
            if not silent:
                self.output_message('Please specify what kind of data you provide.')
            validation_result = False
        
        # If there is an Incoming connection, we need a field containing file/folder names
        if not self.incoming_field:
            if not silent:
                self.output_message('Please select a field from the incoming data containing file names.')
            validation_result = False

        if self.upload_mode == self.UploadMode.UPLOAD_BLOBS and not self.blob_field:
            if not silent:
                self.output_message('Please select a field containing the blob data.')
            validation_result = False

        # Check if a file handling is selected
        if self.upload_mode == self.UploadMode.UPLOAD_FILES and self.file_handling == self.FileHandling.NONE_HANDLING:
            if not silent:
                self.output_message("Please decide what should happen with the files after upload.")
            validation_result = False
        
        if self.upload_mode == self.UploadMode.UPLOAD_FILES and \
            self.file_handling == self.FileHandling.MOVE_FILES and \
                not self.move_path:
            if not silent:
                self.output_message("Please specify a path where the data should be moved to after upload.")
            validation_result = False

        # Check if paths are existent
        if self.sftp_settings['key_filepath']: 
            if not os.path.exists(self.sftp_settings['key_filepath']):
                if not silent:
                    self.output_message('The keyfile could not be found. Please check file path.')
                validation_result = False
            elif not os.path.isfile(self.sftp_settings['key_filepath']):
                if not silent:
                    self.output_message('The path for the keyfile is not a file. Please specify a filename.')
                validation_result = False
        if self.upload_mode == self.UploadMode.UPLOAD_FILES and self.file_handling == self.FileHandling.MOVE_FILES and self.move_path:
            if not os.path.exists(self.move_path):
                if not silent:
                    self.output_message('The specified path for moving the files after upload does not exist. Please create the folder or enter a different path.')
                validation_result = False
            elif not os.path.isdir(self.move_path):
                if not silent:
                    self.output_message('The target path for moving the files is not a directory. Please enter a directory.')
                validation_result = False

        return validation_result

    def _init_sftp(self) -> pysftp.Connection:
        """Sets up the Connection to the SFTP server.
        
        :return: An active connection object
        :rtype: pysftp.Connection
        """
        # SFTP Security: Check for known_hosts
        sftp_cnopts = pysftp.CnOpts()
        sftp_hosts = None
        if sftp_cnopts.hostkeys.lookup(self.sftp_settings['hostname']) is None:
            self.output_message("Unkown host {}. Any host key will be accepted.".format(self.sftp_settings['hostname']),
                                messageType=Sdk.EngineMessageType.warning)
            sftp_hosts = sftp_cnopts.hostkeys
            # DANGER: Disable all key validation for all hosts
            sftp_cnopts.hostkeys = None

        # Initiate connection
        try:
            sftp_conn = pysftp.Connection(host=self.sftp_settings['hostname'],
                                          port=self.sftp_settings['port'],
                                          username=self.sftp_settings['username'],
                                          password=self.sftp_settings['password'],
                                          private_key=self.sftp_settings['key_filepath'],
                                          private_key_pass=self.sftp_settings['key_passphrase'],
                                          cnopts=sftp_cnopts)

            # Add host to known_hosts if not known yet
            if sftp_hosts != None:
                self.output_message("Connected to unknown host. Caching its hostkey to known_hosts.", messageType=Sdk.EngineMessageType.warning)
                sftp_hosts.add(self.sftp_settings['hostname'], sftp_conn.remote_server_key.get_name(), sftp_conn.remote_server_key)
                # Create necessary directories if not yet available
                hosts_file = pysftp.helpers.known_hosts()
                if not os.path.exists(os.path.dirname(hosts_file)):
                    os.mkdir(os.path.dirname(hosts_file))
                sftp_hosts.save(hosts_file)            
        except pysftp.ConnectionException as e:
            self.output_message("Could not connect to server. Please check settings.")
            return False
        except pysftp.CredentialException as e:
            self.output_message("Authentication failed. Please check credentials.")
            return False
        except pysftp.paramiko.BadAuthenticationType as e:
            self.output_message("Unsupported Authentication Type: {}".format(e))
            return False
        except Exception as e:
            self.output_message("Connection error: {}".format(e))
            return False

        # Change working directory
        self.output_message("Connected successfully to {}".format(self.sftp_settings['hostname']), messageType=Sdk.EngineMessageType.info)
        try:
            sftp_conn.chdir(self.sftp_settings['remote_path'])
        except IOError as e:
            self.output_message("Remote path does not exist: {}".format(self.sftp_settings['remote_path']))
            return False

        return sftp_conn

    def pi_init(self, str_xml: str):
        """
        Called when the Alteryx engine is ready to provide the tool configuration from the GUI.
        :param str_xml: The raw XML from the GUI.
        """
        xml = Et.fromstring(str_xml)

        # Getting the user-entered settings from the GUI
        # SFTP Settings
        self.sftp_settings['hostname'] = self._prep_xmltext(xml, 'Hostname')
        self.sftp_settings['port'] = int(self._prep_xmltext(xml, 'Port'))
        self.sftp_settings['username'] = self._prep_xmltext(xml, 'Username')
        self.sftp_settings['password'] = self._prep_xmltext(xml, 'Password')
        self.sftp_settings['key_filepath'] = self._prep_xmltext(xml, 'KeyfilePath')
        if self.sftp_settings['key_filepath']:
            self.sftp_settings['key_passphrase'] = self._prep_xmltext(xml, 'KeyfilePassphrase')
        else:
            self.sftp_settings['key_passphrase'] = None
        self.sftp_settings['remote_path'] = self._prep_xmltext(xml, 'RemotePath')
        # Add trailing slash
        if self.sftp_settings['remote_path']:
            if self.sftp_settings['remote_path'][len(self.sftp_settings['remote_path'])-1] != '/':
                self.sftp_settings['remote_path'] += '/'
        # Tool Mode
        self.upload_mode = {
            'upload_files': self.UploadMode.UPLOAD_FILES,
            'upload_blobs': self.UploadMode.UPLOAD_BLOBS
        }.get(self._prep_xmltext(xml, 'UploadMode'), self.UploadMode.NONE_MODE)
        # File Handling
        self.file_handling = {
            'keep_files': self.FileHandling.KEEP_FILES,
            'delete_files': self.FileHandling.DELETE_FILES,
            'move_files': self.FileHandling.MOVE_FILES
        }.get(self._prep_xmltext(xml, 'FileHandling'), self.FileHandling.NONE_HANDLING)
        self.move_path = self._prep_xmltext(xml, 'MovePath')
        # Trailing slash
        if self.move_path:
            self.move_path = os.path.join(self.move_path, "")
        self.overwrite = (self._prep_xmltext(xml, 'Overwrite') == 'True')
        # Incoming Settings
        self.incoming_field = self._prep_xmltext(xml, 'IncomingField')
        self.blob_field = self._prep_xmltext(xml, 'BlobField')

        # Validate settings
        self.validate_settings()

    def pi_add_incoming_connection(self, str_type: str, str_name: str) -> object:
        """
        The IncomingInterface objects are instantiated here, one object per incoming connection.
        Called when the Alteryx engine is attempting to add an incoming data connection.
        :param str_type: The name of the input connection anchor, defined in the Config.xml file.
        :param str_name: The name of the wire, defined by the workflow author.
        :return: The IncomingInterface object(s).
        """
        self.input_anchor = IncomingInterface(parent=self)
        return self.input_anchor

    def pi_add_outgoing_connection(self, str_name: str) -> bool:
        """
        Called when the Alteryx engine is attempting to add an outgoing data connection.
        :param str_name: The name of the output connection anchor, defined in the Config.xml file.
        :return: True signifies that the connection is accepted.
        """
        return True

    def pi_push_all_records(self, n_record_limit: int) -> bool:
        """
        Called, when no incoming connection is present, i.e. we download all files in the specific directory.
        :param n_record_limit: Set it to <0 for no limit, 0 for no records, and >0 to specify the number of records.
        :return: True for success, False for failure.
        """
        return False

    def pi_close(self, b_has_errors: bool):
        """
        Called after all records have been processed.
        :param b_has_errors: Set to true to not do the final processing.
        """
        pass

    def output_message(self, text: str, messageType = Sdk.EngineMessageType.error):
        """
        Little wrapper for Alteryx Engine expression to show a message
        :param text: Error message.
        :param messageType: Message type in Alteryx (default: error)
        """
        self.alteryx_engine.output_message(self.n_tool_id, messageType, self.xmsg(text))

    @staticmethod
    def _prep_xmltext(et: Et, key: str) -> str:
        """Wrapper to quickly get settings.
        
        :param et: Element Tree from parsed Xml
        :type et: xml.etree.ElementTree
        :param key: Name of the setting
        :type key: str
        :return: Parsed value for setting
        :rtype: str
        """
        t = et.find(key).text.strip() if et.findtext(key) and (et.find(key).text is not None) else None
        return None if not t or t == "" else t
    
    @staticmethod
    def xmsg(msg_string: str) -> str:
        """
        A non-interface, non-operational placeholder for the eventual localization of predefined user-facing strings.
        :param msg_string: The user-facing string.
        :return: msg_string
        """
        return msg_string

class IncomingInterface:
    """
    This optional class is returned by pi_add_incoming_connection, and it implements the incoming interface methods, to
    be utilized by the Alteryx engine to communicate with a plugin when processing an incoming connection.
    Prefixed with "ii", the Alteryx engine will expect the below four interface methods to be defined.
    """

    def __init__(self, parent: AyxPlugin):
        """
        Constructor for IncomingIntreface.
        :param parent: AyxPlugin
        """
        # Reference to AyxPlugin
        self.ayx_plugin = parent
        # RecordInfos in & out
        self.record_info_in = None
        # Input Field
        self.in_field = None
        self.blob_field = None
        # SFTP Connection reference
        self.sftp_conn = None

        self.file_counter = 0

    def ii_init(self, record_info_in: object) -> bool:
        """
        Called to report changes of the incoming connection's record metadata to the Alteyx engine.
        :param record_info_in: A RecordInfo object for the incoming connection's fields.
        :return: True for success, otherwise False.
        """
        self.record_info_in = record_info_in

        if not self.ayx_plugin.incoming_field:
            self.ayx_plugin.output_message("No incoming field selected.")
            return False

        self.in_field = record_info_in.get_field_by_name(self.ayx_plugin.incoming_field, throw_error=False)
        if not self.in_field:
            self.ayx_plugin.output_message('Field "{}" was not found in the incoming data.'.format(self.ayx_plugin.incoming_field))
            return False
        if not (self.in_field.type == Sdk.FieldType.string or \
                self.in_field.type == Sdk.FieldType.wstring or \
                self.in_field.type == Sdk.FieldType.v_string or \
                self.in_field.type == Sdk.FieldType.v_wstring):
            self.ayx_plugin.output_message('Field "{}" is not a string, so cannot contain a file name.'.format(self.in_field.name))
            return False

        # Check if field type matches
        if self.ayx_plugin.upload_mode == self.ayx_plugin.UploadMode.UPLOAD_BLOBS:
            self.blob_field = record_info_in.get_field_by_name(self.ayx_plugin.blob_field, throw_error=False)
            if self.blob_field.type != Sdk.FieldType.blob:
                self.ayx_plugin.output_message('Field "{}" does not contain blobs.'.format(self.in_field.name))
                return False

        self.file_counter = 0

        return True

    def ii_push_record(self, in_record: object) -> bool:
        """
        Called when an input record is being sent to the plugin.
        :param in_record: The data for the incoming record.
        :return: False if method calling limit is hit.
        """
        if (in_record is None) or (self.ayx_plugin.alteryx_engine.get_init_var(self.ayx_plugin.n_tool_id, 'UpdateOnly') == 'True'):
            return False

        # Validate settings
        if not self.ayx_plugin.validate_settings(silent=False):
            return False
        if not self.in_field:
            return False

        # If we do not yet have a connection, we need to connect
        if not self.sftp_conn:
            self.sftp_conn = self.ayx_plugin._init_sftp()
            if not self.sftp_conn:
                return False


        # Current file
        if self.ayx_plugin.upload_mode == self.ayx_plugin.UploadMode.UPLOAD_FILES:
            cur_fpath = self.in_field.get_as_string(in_record)
            # Check whether local file exists
            if not os.path.exists(cur_fpath):
                self.ayx_plugin.output_message('File "{}" does not exist.'.format(cur_fpath))
                return True
            # Check whether file is actually a file
            if not os.path.isfile(cur_fpath):
                self.ayx_plugin.output_message('File "{}" is actually a folder. Please provide a file name.'.format(cur_fpath))
                return True

            _, cur_fname = os.path.split(cur_fpath)
            # Check whether remote file exists already
            if self.sftp_conn.exists(cur_fname) and not self.ayx_plugin.overwrite:
                self.ayx_plugin.output_message('File "{}{}" already exists. Skipped.'.format(self.ayx_plugin.sftp_settings['remote_path'], cur_fname),
                                               messageType=Sdk.EngineMessageType.warning)
                return True

            # Upload file
            try:
                self.sftp_conn.put(cur_fpath)
            except (IOError, OSError) as e:
                self.ayx_plugin.output_message('File "{}" could not be uploaded: {}'.format(cur_fname, e))
            else:
                self.ayx_plugin.output_message('{} successfully uploaded to {}{}'.format(cur_fname, self.ayx_plugin.sftp_settings['remote_path'], cur_fname),
                                               messageType=Sdk.Status.info)

            if self.ayx_plugin.file_handling == self.ayx_plugin.FileHandling.DELETE_FILES:
                # Delete current file
                try:
                    os.remove(cur_fpath)
                except Exception as e:
                    self.ayx_plugin.output_message('Could not delete "{}": {}'.format(cur_fpath, e))
            elif self.ayx_plugin.file_handling == self.ayx_plugin.FileHandling.MOVE_FILES:
                # Move current file to target path
                new_fpath = os.path.join(self.ayx_plugin.move_path, cur_fname)
                try:
                    os.rename(cur_fpath, new_fpath)
                except Exception as e:
                    self.ayx_plugin.output_message('Could not move "{}" to "{}": {}'.format(cur_fpath, new_fpath, e))
        elif self.ayx_plugin.upload_mode == self.ayx_plugin.UploadMode.UPLOAD_BLOBS:
            cur_fname = self.in_field.get_as_string(in_record)
            # Check whether file name is not empty
            if not cur_fname:
                self.ayx_plugin.output_message('No filename provided. Cannot upload.')
                return True
            # Check whether remote file already exists
            if self.sftp_conn.exists(cur_fname) and not self.ayx_plugin.overwrite:
                self.ayx_plugin.output_message('File "{}{}" already exists. Skipped.'.format(self.ayx_plugin.sftp_settings['remote_path'], cur_fname),
                                               messageType=Sdk.EngineMessageType.warning)
                return True
            
            cur_blob = self.blob_field.get_as_blob(in_record)
            cur_datafo = io.BytesIO(cur_blob)
            try:
                self.sftp_conn.putfo(cur_datafo, cur_fname)
            except (TypeError, IOError) as e:
                self.ayx_plugin.output_message('Error uploading {}: {}'.format(cur_fname, e))
            else:
                self.ayx_plugin.output_message('{} successfully uploaded to {}{}'.format(cur_fname, self.ayx_plugin.sftp_settings['remote_path'], cur_fname),
                                               messageType=Sdk.Status.info)

        self.file_counter += 1

        return True

    def ii_update_progress(self, d_percent: float):
        """
        Called by the upstream tool to report what percentage of records have been pushed.
        :param d_percent: Value between 0.0 and 1.0.
        """
        self.ayx_plugin.alteryx_engine.output_tool_progress(self.ayx_plugin.n_tool_id, d_percent)  # Inform the Alteryx engine of the tool's progress.

    def ii_close(self):
        """
        Called when the incoming connection has finished passing all of its records.
        """
        if self.sftp_conn:
            self.sftp_conn.close()
            self.sftp_conn = None
    