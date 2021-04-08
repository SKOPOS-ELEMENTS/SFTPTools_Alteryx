# Alteryx Tools for SFTP Transfers

![Downloader Icon](SKOPOSSFTPDownload_v1/SKOPOSSFTPDownload_v1.0Icon.png "Downloader Icon")
![Uploader Icon](SKOPOSSFTPUpload_v1.0/SKOPOSSFTPUpload_v1.0Icon.png "Uploader Icon")

This is a bundle of two [Alteryx](https://www.alteryx.com/products/alteryx-platform/alteryx-designer) tools for exchanging files with an SFTP server. (As of today, only the download tool is available.) The tools are built using the Python SDK and require only the fantastic `pysftp` and it's dependecies (notably, `paramiko`) and should be rather efficient.

## Features

* Connect to SFTP servers
* Supports authentication using public/private key (with OpenSSH compatible key files)
* Download files from an SFTP server
    * List all files in a remote directory, incl. file attributes
    * Download all files in a remote directory
    * Download files from a remote directory as specified in an input data stream
    * Download files to a local path _or_ to a blob field in your workflow
    * Move or delete files on the server after successful download
* Upload files to an SFTP server
    * Upload files from local or network resource by providing their filepath
    * Upload files stored as blob fields in your data stream
    * Move or delete files after successful upload

## Password Security and Alteryx Server

Please note: **Passwords will be stored in plain-text in your workflow!** If you enter a password for the SFTP connection, this password will be stored in plain-text as part of your workflow's XML. That means, anyone can read the password using a text editor.

Alteryx currently does not support a flexible way of storing encrypted passwords in workflows, that also works when using the Alteryx Server. While the Python SDK allows to store encrypted strings, the passwords can only be decrypted on the same machine and/or the same user. When you have an Alteryx Server running with a dedicated user (as is the recommended setup), Alteryx Server cannot decrypt the passwords and the SFTP tools will not work.

More generally, key files are a better way to access SFTP servers. So, if you have the chance to set up the SFTP server using public-private-key authentication you should do so. You can specify the path to a private key in the SFTP tools. If you want to use the tools in a workflow on the server, specify the path as UNC (e.g. `\\fileserver\my\private\folder.ppk`) and make sure that the user running the workflows on the server has access to this file.

We will update the tools as soon as the Python SDK allows for better credential management on the Alteryx Server. If you have an alternative solution, feel free to create [pull request](https://help.github.com/en/github/collaborating-with-issues-and-pull-requests/creating-a-pull-request).

## Installation

Simply download from the [Releases page](https://github.com/SKOPOS-ELEMENTS/SFTPTools_Alteryx/releases) and open the *yxi* with Alteryx (e.g. double clicking the file).

If you want to install the tools for all users on your machine, remember to run Alteryx with administrator privileges before opening the *.yxi*. Especially if you want to use the tools on Alteryx Server.

### Build from Source

After making changes to the source, you might want to re-build the *yxi* installer. The repository contains a small script to zip all files and create the *.yxi* file:

```
> ./build-yxi-installer.sh
```

The provided Shell script was developed for macOS. It might work in Windows' Linux subsystem, but we cannot provide support for this.

If you want to build the *yxi* under Windows, please follow the [instructions in the Alteryx help](https://help.alteryx.com/developer/current/PackageTool.htm?tocpath=SDKs%7CBuild%20Custom%20Tools%7C_____7).

To continue working on the tools, you should know what to do or start with an [introduction on the Alteryx SDKs](https://help.alteryx.com/developer/current/SDK/ToolQuickStart.htm?tocpath=SDKs%7CBuild%20Custom%20Tools%7C_____1).

