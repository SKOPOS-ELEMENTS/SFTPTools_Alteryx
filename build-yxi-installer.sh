#!/bin/bash
# Make sure to use LF line-endings!

# Store current directory - from here we take all the files
DIR="$(cd "$( dirname "${BAShSOURCE[0]}" )" && pwd)"

# Create and use temp directory here
WORK_DIR=`mktemp -d -t BuildAlteryxInstaller`

# Check if we have a temporary directory
if [[ ! "$WORK_DIR" || ! -d "$WORK_DIR" ]]; then
    echo "Could not create temp dir"
    exit 1
fi

# Deletes the temp directory
function cleanup {
    rm -rf "$WORK_DIR"
    echo "Deleted temp working directory $WORK_DIR"
}

# Register cleanup function to be called on the EXIT signal
trap cleanup EXIT

rm "$DIR/Dist/*.yxi"

# No let's do some work
mkdir "$WORK_DIR/SKOPOS_SFTP_Tools_v1.0/"
mkdir "$WORK_DIR/SKOPOS_SFTP_Tools_v1.0/SKOPOSSFTPDownload_v1.0/"
mkdir "$WORK_DIR/SKOPOS_SFTP_Tools_v1.0/SKOPOSSFTPUpload_v1.0/"
cp -v "$DIR/SKOPOSSFTPDownload_v1.0/SKOPOSSFTPDownload_v1.0"* "$WORK_DIR/SKOPOS_SFTP_Tools_v1.0/SKOPOSSFTPDownload_v1.0/"
cp -v "$DIR/SKOPOSSFTPUpload_v1.0/SKOPOSSFTPUpload_v1.0"* "$WORK_DIR/SKOPOS_SFTP_Tools_v1.0/SKOPOSSFTPUpload_v1.0/"
cp -v "$DIR/requirements.txt" "$WORK_DIR/SKOPOS_SFTP_Tools_v1.0/SKOPOSSFTPDownload_v1.0/"
cp -v "$DIR/requirements.txt" "$WORK_DIR/SKOPOS_SFTP_Tools_v1.0/SKOPOSSFTPUpload_v1.0/"
cp -v "$DIR/Assets/Installer_Config.xml" "$WORK_DIR/SKOPOS_SFTP_Tools_v1.0/Config.xml"

cd "$WORK_DIR/SKOPOS_SFTP_Tools_v1.0"
mkdir "$DIR/Dist/"
zip -r "$DIR/Dist/SKOPOS_SFTP_Tools_v1.0.yxi" * 
cd "$DIR"