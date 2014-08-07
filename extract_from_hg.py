#!/usr/bin/python

##
# This script is designed to import Loop standalone content from
# mozilla-central, to the git repo, with necessary translations of
# file locations, and some in-file corrections.
#
# It is typically expected to be run from a cron job.
#
# It expects to be run in the root directory of
# https://github.com/mozilla/loop-client
# and expects http://hg.mozilla.org/mozilla-central/ to be in
# "../mozilla-central"
#
# It also assumes the "origin" remote is correctly set on the repository
##

import argparse
import os
from datetime import datetime
import subprocess
import pytz, dateutil, dateutil.tz
from mercurial import hg, ui, commands
# We use gitpython for the repository operational commands, e.g. push and
# pull, because that's easier. Unfortunately gitpython doesn't seem to want
# to set dates on commits, so we revert to calling git directly for that.
from git import *

LATEST_REV_FILE = "last_m_c_import_rev.txt"
M_C_SOURCE_URL = "http://hg.mozilla.org/mozilla-central/"
M_C_SOURCE_REPO = "../mozilla-central"

# Is this interesting to Loop?
def interestingFilename(filename):
    return (filename.startswith("browser/components/loop/standalone") or
            filename.startswith("browser/components/loop/content/shared") or
            filename.startswith("browser/components/loop/test/standalone") or
            filename.startswith("browser/components/loop/test/shared"))

# This is how we map files from mozilla-central to loop-client repo
def translateFilename(filename):
    filename = filename.replace("browser/components/loop/standalone/", "")
    filename = filename.replace("browser/components/loop/content/shared/", "content/shared/")
    filename = filename.replace("browser/components/loop/test/standalone/", "test/standalone/")
    filename = filename.replace("browser/components/loop/test/shared/", "test/shared/")
    return filename

def testFileNeedsTranslation(filename):
    return (filename == "test/standalone/index.html" or
            filename == "test/shared/index.html")

def translateTestFile(filename, fileContext):
    print "Translating %s" % filename
    return fileContext.data().replace('src="../../standalone/', 'src="../../')

# Write a file out to disk, fileContext is the hg file context.
def writeFile(filename, fileContext):
    outFile = open(filename, "w")
    if testFileNeedsTranslation(filename):
        outFile.write(translateTestFile(filename, fileContext))
    else:
        outFile.write(fileContext.data())
    outFile.close()

def deleteFile(filename):
    os.remove(filename)

def gitAdd(filename):
    cmd = ['git', 'add', filename]
    p = subprocess.Popen(cmd)
    p.wait()

def gitRemove(filename):
    cmd = ['git', 'rm', filename]
    p = subprocess.Popen(cmd)
    p.wait()

# Deals with writing all parts of a cset to disk, updating the git index
# as we go.
def writeCset(cset):
    print "%s %s" % (cset.hex(), cset.description())

    for filename in cset.files():
        # Write the files
        if interestingFilename(filename):
            newFilename = translateFilename(filename)
            try:
                fileData = cset[filename]
            except:
                # print "Deleting file %s" % (filename)
                deleteFile(newFilename)
                gitRemove(newFilename)
            else:
                # print "Writing %s to %s" % (filename, newFilename)
                writeFile(newFilename, fileData)
                gitAdd(newFilename)

# Actually commits the cset
def commitCset(cset):
    commitMsg = "%s\nmozilla-central hg revision: %s" % (cset.description(), cset.hex())
    csetDate = datetime.fromtimestamp(cset.date()[0], dateutil.tz.tzoffset(None, -cset.date()[1]))
    cmd = ['git', 'commit', '-m', commitMsg, '--author=' + cset.user(),
           '--date=' + str(csetDate)]
    p = subprocess.Popen(cmd)
    p.wait()

# Outputs to the lastest revision file
def writeLatestRev(cset):
    outFile = open(LATEST_REV_FILE, "w")
    outFile.write(cset.hex() + "\n")
    outFile.close()

    gitAdd(LATEST_REV_FILE)
    cmd = ['git', 'commit', '-m', 'update latest merged cset file']
    p = subprocess.Popen(cmd)
    p.wait()

def updateRepos(hgRepo, hgUI):
    # And update it
    if commands.incoming(hgUI, hgRepo, source=M_C_SOURCE_URL, bundle=None, force=None) == 0:
        commands.pull(hgUI, hgRepo, source=M_C_SOURCE_URL)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--push-result', dest='push_result', action='store_true',
                        default=False,
                        help='Push the result of the extraction')

    args = parser.parse_args()

    # First of all, check we're up to date for the git repo.
    gitRepo = Repo(".")
    assert gitRepo.bare == False
    assert gitRepo.is_dirty() == False

    print gitRepo.active_branch
    gitOrigin = gitRepo.remote("origin")
    gitOrigin.pull()

    # Find out the last revision we checked against
    lastestRevFile = open(LATEST_REV_FILE, "r")
    firstRevText = lastestRevFile.read().strip()
    lastestRevFile.close()

    print "Starting at %s" % (firstRevText)

    # Last revision to check to.
    lastRevText = "default"

    # Open the Mercurial repo...
    hgUI = ui.ui()
    hgRepo = hg.repository(hgUI, M_C_SOURCE_REPO)

    updateRepos(hgRepo, hgUI)

    committedFiles = False
    print firstRevText
    print lastRevText
    firstRev = hgRepo[firstRevText].rev()
    lastRev = hgRepo[lastRevText].rev()

    # Now work through any new changesets
    for i in xrange(firstRev, lastRev):
        cset = hgRepo[i]

        # Use the very last cset, not the one that affects loop,
        # to avoid attempting to port the same cset all the time
        lastCset = cset

        if "merge" in cset.description().lower():
            continue

        affectsLoop = False
        # If one of the files is interesting to loop, then we need to
        # do the whole changeset
        for filename in cset.files():
            if interestingFilename(filename):
                print filename
                affectsLoop = True
                break

        if affectsLoop:
            # Create a new index for the repo (indexes get translated
            # into commits)
            # Write the cset, then commit it.
            writeCset(cset)
            commitCset(cset)
            committedFiles = True

    # Only bother committing if we're updated the files.
    # In theory we shouldn't need to commit anyway, but it
    # may be a useful check
    if committedFiles:
        writeLatestRev(lastCset)

    if args.push_result:
        gitRepo.push()

if __name__ == "__main__":
    main()

