"""
AyxPlugin (required) has-a IncomingInterface (optional).
Although defining IncomingInterface is optional, the interface methods are needed if an upstream tool exists.
"""

import re
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

    class ToolMode(Enum):
        NONE_MODE = 0
        LIST_FILES = 1
        DOWNLOAD_TO_PATH = 2
        DOWNLOAD_TO_BLOB = 3

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
            'remote_path': '/',
            'move_path': None
        })
        # Tool mode: What should we do?
        self.tool_mode = self.ToolMode.NONE_MODE
        self.output_settings = dict({
            'local_path': None,
            'blobfield': 'DownloadedData'
        })
        self.file_handling = self.FileHandling.NONE_HANDLING
        # Incoming Interface settings
        self.incoming_field = None

        # Storage
        self.input_optional = None
        self.input_recordinfo = None
        self.output_anchor = None
        self.output_recordinfo = None

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

        if self.tool_mode == self.ToolMode.NONE_MODE:
            if not silent:
                self.output_message('Please select a mode for the tool.')
            validation_result = False
        
        if self.tool_mode == self.ToolMode.DOWNLOAD_TO_PATH and not self.output_settings['local_path']:
            if not silent:
                self.output_message('Please enter a path to store downloaded files.')
            validation_result = False

        # Check if a file handling is selected
        if self.tool_mode != self.ToolMode.LIST_FILES and self.file_handling == self.FileHandling.NONE_HANDLING:
            if not silent:
                self.output_message("Please decide what should happen with the files after download.")
            validation_result = False
        
        if self.tool_mode != self.ToolMode.LIST_FILES and \
            self.file_handling == self.FileHandling.MOVE_FILES and \
                not self.sftp_settings['move_path']:
            if not silent:
                self.output_message("Please specify a path where the data should be moved to.")
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
        if self.tool_mode == self.ToolMode.DOWNLOAD_TO_PATH and self.output_settings['local_path']:
            if not os.path.exists(self.output_settings['local_path']):
                if not silent:
                    self.output_message('The specified path for the output does not exist. Please create the folder or enter a different path.')
                validation_result = False
            elif not os.path.isdir(self.output_settings['local_path']):
                if not silent:
                    self.output_message('The output path is not a directory. Please enter a directory.')
                validation_result = False

        # If there is an Incoming connection, we need a field containing file/folder names
        if self.input_optional and not self.incoming_field:
            if not silent:
                self.output_message('Please select a field from the incoming data containing file/folder names.')
            validation_result = False

        return validation_result

    def _list_to_recordinfo(self, rec_info: Sdk.RecordInfo, field_list: list, source: str = "SFTP Downloader"):
        """Adds fields to RecordInfo according to list
        
        :param rec_info: RecordInfo object to which fields are to be added
        :type rec_info: Sdk.RecordInfo
        :param field_list: List of dict() containing field information
        :type field_list: list
        """

        # Iterate through list
        for field in field_list:
            rec_info.add_field(field['name'], field['type'], field['size'], source=source, description=field['description'])

        return

    def build_ayx_output(self, push_metadata: bool = True):
        """Generates everything needed to push data downstream.

        Creates Record Info construct and Record Creator along with a dictionary containing the indices.
        :param push_metadata: If True, meta-data will automatically pushed downstream
        :type push_metadata: bool
        :return: Tuple of RecordInfo, RecordCreator, list()
        :rtype: RecordInfo, RecordCreator, list
        """

        rec_info = Sdk.RecordInfo(self.alteryx_engine)
        field_list = list()

        # Generate list of fields according to tool mode
        if self.tool_mode == self.ToolMode.LIST_FILES:
            # Build RecordInfo object for output
            field_list = [
                {'name': "Filename",      'type': Sdk.FieldType.v_wstring, 'size': 12345678, 'description': "Filename"},
                {'name': "Size",          'type': Sdk.FieldType.int32,     'size': 32,       'description': "File Size"},
                {'name': "UID",           'type': Sdk.FieldType.v_wstring, 'size': 12345678, 'description': "User ID of Owner"},
                {'name': "GID",           'type': Sdk.FieldType.v_wstring, 'size': 12345678, 'description': "Group ID of Owner"},
                {'name': "Mode",          'type': Sdk.FieldType.v_wstring, 'size': 12345678, 'description': "File Mode"},
                {'name': "TimeAdded",     'type': Sdk.FieldType.datetime,  'size': 19,       'description': "Time Added"},
                {'name': "TimeModified",  'type': Sdk.FieldType.datetime,  'size': 12345678, 'description': "Time Modified"},
                {'name': "IsDirectory",   'type': Sdk.FieldType.bool,      'size': 0,        'description': "Is item a directory?"},
                {'name': "IsFile",        'type': Sdk.FieldType.bool,      'size': 0,        'description': "Is item a file?"}
            ]
        else:
            field_list = [
                {'name': "Filename",      'type': Sdk.FieldType.v_wstring, 'size': 12345678, 'description': "Filename"},
                {'name': "Size",          'type': Sdk.FieldType.int32,     'size': 32,       'description': "File Size"},
                {'name': "TimeAdded",     'type': Sdk.FieldType.datetime,  'size': 19,       'description': "Time Added"},
                {'name': "TimeModified",  'type': Sdk.FieldType.datetime,  'size': 12345678, 'description': "Time Modified"}
            ]
            if self.tool_mode == self.ToolMode.DOWNLOAD_TO_BLOB:
                # Data will contain a Blob-Field containing the files
                field_list.append(
                    {'name': self.output_settings['blobfield'], 'type': Sdk.FieldType.blob, 'size': 123456789, 'description': "File Contents as Blob"}
                )
            elif self.tool_mode == self.ToolMode.DOWNLOAD_TO_PATH:
                # Data will contain a path to the local copy of the file
                field_list.append(
                    {'name': "FilePath", 'type': Sdk.FieldType.v_wstring, 'size': 123456789, 'description': "Local File Path"}
                )

        # Add fields to RecordInfo object
        self._list_to_recordinfo(rec_info, field_list, source="SFTP Downloader: {}".format(self.sftp_settings['hostname']))

        # Push meta data downstream
        if push_metadata:
            self.output_anchor.init(rec_info)

        # Get a record creator
        rec_creator = rec_info.construct_record_creator()

        # Generate a list of names and IDs, so we can make sure to fill the right fields
        field_dict = {a['name']: idx for idx, a in enumerate(field_list)}

        return rec_info, rec_creator, field_dict
  
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
        if not sftp_conn.isdir(self.sftp_settings['remote_path']):
            self.output_message('Remote path "{}" is not a directory.'.format(self.sftp_settings['remote_path']))
            return False
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
        self.sftp_settings['move_path'] = self._prep_xmltext(xml, 'MovePath')
        # Tool Mode
        self.tool_mode = {
            'list': self.ToolMode.LIST_FILES,
            'download_file': self.ToolMode.DOWNLOAD_TO_PATH,
            'download_blob': self.ToolMode.DOWNLOAD_TO_BLOB
        }.get(self._prep_xmltext(xml, 'ToolMode'), self.ToolMode.NONE_MODE)
        # File Handling
        self.file_handling = {
            'keep_files': self.FileHandling.KEEP_FILES,
            'delete_files': self.FileHandling.DELETE_FILES,
            'move_files': self.FileHandling.MOVE_FILES
        }.get(self._prep_xmltext(xml, 'FileHandling'), self.FileHandling.NONE_HANDLING)
        # Output Settings
        if self.tool_mode == self.ToolMode.DOWNLOAD_TO_PATH:
            self.output_settings['local_path'] = self._prep_xmltext(xml, 'LocalPath')
            self.output_settings['local_path'] = os.path.join(self.output_settings['local_path'], "")
        else:
            self.output_settings['local_path'] = None
        # Incoming Settings
        self.incoming_field = self._prep_xmltext(xml, 'IncomingField')

        # Validate settings
        self.validate_settings()
                
        # Get Output anchors
        self.output_anchor = self.output_anchor_mgr.get_output_anchor('Output')

    def pi_add_incoming_connection(self, str_type: str, str_name: str) -> object:
        """
        The IncomingInterface objects are instantiated here, one object per incoming connection.
        Called when the Alteryx engine is attempting to add an incoming data connection.
        :param str_type: The name of the input connection anchor, defined in the Config.xml file.
        :param str_name: The name of the wire, defined by the workflow author.
        :return: The IncomingInterface object(s).
        """
        self.input_optional = IncomingInterface(parent=self)
        return self.input_optional

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
        # Don't get data when data is not actually requested
        if self.alteryx_engine.get_init_var(self.n_tool_id, 'UpdateOnly') == 'True':
            if self.output_recordinfo is not None:
                # If we have record info from last time, just push it downstream
                self.output_anchor.init(self.output_recordinfo)
            return False

        # Validate settings, otherwise do not do anything
        if not self.validate_settings(silent=True):
            return False
        
        # Let's get going...
        # Reset progress
        self.output_anchor.update_progress(0)

        # Prepare SFTP-connection
        sftp_conn = self._init_sftp()
        if not sftp_conn:
            # Something went wrong
            return False

        # Collect all files and directories
        # We need it for any tool mode, so we collect it once
        file_list = list()
        sftp_files = sftp_conn.listdir_attr()
        for fattr in sftp_files:
            file_list.append({
                'filename': str(fattr.filename),
                'size': int(fattr.st_size),
                'uid': str(fattr.st_uid),
                'gid': str(fattr.st_gid),
                'mode': str(pysftp.st_mode_to_int(fattr.st_mode)),
                'atime': datetime.utcfromtimestamp(int(fattr.st_atime)).strftime("%Y-%m-%d %H:%M:%S"),
                'mtime': datetime.utcfromtimestamp(int(fattr.st_mtime)).strftime("%Y-%m-%d %H:%M:%S"),
                'is_file': sftp_conn.isfile(fattr.filename),
                'is_dir': sftp_conn.isdir(fattr.filename)
            })
        
        # Get everything Alteryx needs
        self.output_recordinfo, record_creator, field_dict = self.build_ayx_output(push_metadata=True)

        # Iterate through all files in current directory
        item_counter = -1
        for f in file_list:
            # Update progress
            item_counter += 1
            self.output_anchor.update_progress(item_counter / float(len(file_list)))

            if not f['is_file'] and self.tool_mode != self.ToolMode.LIST_FILES:
                # If not a file, do not download
                self.output_message('"{}{}" is not a file. Skipped.'.format(self.sftp_settings['remote_path'], f['filename']),
                                    messageType=Sdk.EngineMessageType.warning)
                continue

            # Process file
            self._process_file(sftp_conn, f, field_dict, self.output_recordinfo, record_creator)

        # Close connection
        sftp_conn.close()

        # Log Tool input
        if self.tool_mode == self.ToolMode.LIST_FILES:
            inp_msg = "{} items in found in directory {}{}".format(len(file_list), self.sftp_settings['hostname'], self.sftp_settings['remote_path'])
        else:
            inp_msg = "{} files downloaded from {}{}".format(len([1 for f in file_list if f['is_file']]), self.sftp_settings['hostname'], self.sftp_settings['remote_path'])
        self.output_message(inp_msg, messageType=Sdk.Status.info)

        self.output_anchor.update_progress(1)
        self.output_anchor.close()
        return True

    def pi_close(self, b_has_errors: bool):
        """
        Called after all records have been processed.
        :param b_has_errors: Set to true to not do the final processing.
        """

        self.output_anchor.assert_close()

    def output_message(self, text: str, messageType = Sdk.EngineMessageType.error):
        """
        Little wrapper for Alteryx Engine expression to show a message
        :param text: Error message.
        :param messageType: Message type in Alteryx (default: error)
        """
        self.alteryx_engine.output_message(self.n_tool_id, messageType, self.xmsg(text))
    
    def _process_file(self, sftp_conn: pysftp.Connection, f: dict, field_dict: dict, record_info: object, record_creator: object):
        """Process single remote file.
        
        :param sftp_conn: [description]
        :type sftp_conn: pysftp.Connection
        :param f: [description]
        :type f: dict
        :param field_dict: [description]
        :type field_dict: dict
        :param record_creator: [description]
        :type record_creator: object
        """
        # These fields are shared by all tool modes (directories only for LIST_FILES)
        record_info[field_dict['Filename']].set_from_string(record_creator, f['filename'])
        record_info[field_dict['Size']].set_from_int32(record_creator, f['size'])
        record_info[field_dict['TimeAdded']].set_from_string(record_creator, f['atime'])
        record_info[field_dict['TimeModified']].set_from_string(record_creator, f['mtime'])

        if self.tool_mode == self.ToolMode.LIST_FILES:
            # Fields only present for LIST_FILES mode
            record_info[field_dict['UID']].set_from_string(record_creator, f['uid'])
            record_info[field_dict['GID']].set_from_string(record_creator, f['gid'])
            record_info[field_dict['Mode']].set_from_string(record_creator, f['mode'])
            record_info[field_dict['IsDirectory']].set_from_bool(record_creator, f['is_dir'])
            record_info[field_dict['IsFile']].set_from_bool(record_creator, f['is_file'])
        elif self.tool_mode != self.ToolMode.LIST_FILES:
            # Download files if not in LIST_FILES mode
            if self.tool_mode == self.ToolMode.DOWNLOAD_TO_BLOB:
                # Generate temporary filename
                out_fname = self.alteryx_engine.create_temp_file_name('tmp')
            elif self.tool_mode == self.ToolMode.DOWNLOAD_TO_PATH:
                # Build local path for download
                out_fname = os.path.join(self.output_settings['local_path'], f['filename'])
            
            # Download file
            try:
                # Download file to temporary folder
                sftp_conn.get(f['filename'], localpath=out_fname)
            except IOError as e:
                self.output_message('Error transferring file "{}": {}'.format(f['filename'], e))

            # Generate BLOB for Alteryx
            if self.tool_mode == self.ToolMode.DOWNLOAD_TO_BLOB:
                # Read file as binary for blob
                with open(out_fname, 'rb') as temp_f:
                    blob_content = temp_f.read()
            
            if self.tool_mode == self.ToolMode.DOWNLOAD_TO_BLOB:
                # Add file as blob
                record_info[field_dict[self.output_settings['blobfield']]].set_from_blob(record_creator, blob_content)
            elif self.tool_mode == self.ToolMode.DOWNLOAD_TO_PATH:
                # Add file path
                record_info[field_dict['FilePath']].set_from_string(record_creator, out_fname)

        # Finalize record for this file and push
        out_record = record_creator.finalize_record()
        self.output_anchor.push_record(out_record, False)
        # Reset for next file
        record_creator.reset()

        # Handle file after it has been downloaded
        if self.file_handling == self.FileHandling.MOVE_FILES:
            # Check if target folder exists
            if not sftp_conn.exists(self.sftp_settings['move_path']):
                self.output_message("The target folder {} does not exist.".format(self.sftp_settings['move_path']),
                                    messageType=Sdk.EngineMessageType.warning)
                return

            # Check if it is actually a folder
            if not sftp_conn.isdir(self.sftp_settings['move_path']):
                self.output_message("The target folder {} is not a directory.".format(self.sftp_settings['move_path']),
                                    messageType=Sdk.EngineMessageType.warning)
                return

            # Try to move file
            try:
                sftp_conn.rename(sftp_conn.pwd + "/" + f['filename'],
                                 sftp_conn.normalize(self.sftp_settings['move_path']) + "/" + f['filename'])
            except IOError as e:
                self.output_message('Error moving file "{}": {}'.format(f['filename'], e))
            else:
                self.output_message('File {} moved to {}.'.format(f['filename'], sftp_conn.normalize(self.sftp_settings['move_path'])),
                                    messageType=Sdk.EngineMessageType.info)
        elif self.file_handling == self.FileHandling.DELETE_FILES:
            # Simply delete file
            try:
                sftp_conn.remove(sftp_conn.pwd + "/" + f['filename'])
            except IOError as e:
                self.output_message('Error deleting file "{}": {}'.format(f['filename'], e))
            else:
                self.output_message('File {} deleted from server.'.format(f['filename']),
                                    messageType=Sdk.EngineMessageType.info)
            
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
        self.record_info_out = None
        # Input Field
        self.in_field = None
        # Record Creator for outputs
        self.record_creator = None
        self.field_dict = dict()
        # SFTP Connection reference
        self.sftp_conn = None

        self.file_counter = 0

    def ii_init(self, record_info_in: object) -> bool:
        """
        Called to report changes of the incoming connection's record metadata to the Alteyx engine.
        :param record_info_in: A RecordInfo object for the incoming connection's fields.
        :return: True for success, otherwise False.
        """
        if not self.ayx_plugin.incoming_field:
            self.ayx_plugin.output_message("No incoming field selected.")
            return False

        self.in_field = record_info_in.get_field_by_name(self.ayx_plugin.incoming_field, throw_error=False)
        if not self.in_field:
            self.ayx_plugin.output_message('Field "{}" was not found in the incoming data.'.format(self.ayx_plugin.incoming_field))
            return False

        # Build everything for outputting data
        self.record_info_out, self.record_creator, self.field_dict = self.ayx_plugin.build_ayx_output(push_metadata=True)
        self.ayx_plugin.output_recordinfo = self.record_info_out

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

        if self.ayx_plugin.tool_mode == self.ayx_plugin.ToolMode.LIST_FILES:
            self.ayx_plugin.output_message('"List Files" is not supported when filenames are provided through an incoming connection.')
            return False

        # If we do not yet have a connection, we need to connect
        if not self.sftp_conn:
            self.sftp_conn = self.ayx_plugin._init_sftp()
            if not self.sftp_conn:
                return False

        # Current file
        cur_fname = self.in_field.get_as_string(in_record)
        # Check whether file exists
        if not self.sftp_conn.exists(cur_fname):
            self.ayx_plugin.output_message('File "{}{}" does not exist. Skipped.'.format(self.ayx_plugin.sftp_settings['remote_path'], cur_fname),
                                           messageType=Sdk.EngineMessageType.warning)
            return True

        # Check if it is actually a file
        if not self.sftp_conn.isfile(cur_fname):
            self.ayx_plugin.output_message('File "{}{}" is actually a folder. Skipped.'.format(self.ayx_plugin.sftp_settings['remote_path'], cur_fname),
                                           messageType=Sdk.EngineMessageType.warning)
            return True
    
        # Get details on the file
        fattr = self.sftp_conn.stat(cur_fname)
        cur_f = {
            'filename': str(cur_fname),
            'size': int(fattr.st_size),
            'uid': str(fattr.st_uid),
            'gid': str(fattr.st_gid),
            'mode': str(pysftp.st_mode_to_int(fattr.st_mode)),
            'atime': datetime.utcfromtimestamp(int(fattr.st_atime)).strftime("%Y-%m-%d %H:%M:%S"),
            'mtime': datetime.utcfromtimestamp(int(fattr.st_mtime)).strftime("%Y-%m-%d %H:%M:%S")
        }

        # Process file
        self.ayx_plugin._process_file(self.sftp_conn, cur_f, self.field_dict, self.record_info_out, self.record_creator)

        # Update Record Counts downstream
        self.ayx_plugin.output_anchor.output_record_count(False)
        self.file_counter += 1

        return True

    def ii_update_progress(self, d_percent: float):
        """
        Called by the upstream tool to report what percentage of records have been pushed.
        :param d_percent: Value between 0.0 and 1.0.
        """
        self.ayx_plugin.alteryx_engine.output_tool_progress(self.ayx_plugin.n_tool_id, d_percent)  # Inform the Alteryx engine of the tool's progress.
        self.ayx_plugin.output_anchor.update_progress(d_percent)  # Inform the downstream tool of this tool's progress.

    def ii_close(self):
        """
        Called when the incoming connection has finished passing all of its records.
        """
        if self.sftp_conn:
            self.sftp_conn.close()
            self.sftp_conn = None

        if self.ayx_plugin.tool_mode == self.ayx_plugin.ToolMode.LIST_FILES:
            inp_msg = "{} items in found in directory {}{}".format(self.file_counter, self.ayx_plugin.sftp_settings['hostname'], self.ayx_plugin.sftp_settings['remote_path'])
        else:
            inp_msg = "{} files downloaded from {}{}".format(self.file_counter, self.ayx_plugin.sftp_settings['hostname'], self.ayx_plugin.sftp_settings['remote_path'])
        self.ayx_plugin.output_message(inp_msg, messageType=Sdk.Status.info)
        self.ayx_plugin.output_anchor.output_record_count(True)  # True: Let Alteryx engine know that all records have been sent downstream.
        self.ayx_plugin.output_anchor.close()  # Close outgoing connections.
    