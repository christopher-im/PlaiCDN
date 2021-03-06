#!/usr/bin/env python3
#script is a replacement for https://github.com/Relys/3DS_Multi_Decryptor/blob/master/to3DS/CDNto3DS/CDNto3DS.py
#requires PyCrypto to be installed ("python3 -m ensurepip" then "pip3 install PyCrypto")
#requires makerom (https://github.com/profi200/Project_CTR/releases)
#this is a Python 3 script

from xml.dom import minidom
from subprocess import DEVNULL, STDOUT, call, check_call
from struct import pack, unpack
from binascii import hexlify, unhexlify
from Crypto.Cipher import AES
from hashlib import sha256
from imp import reload
import platform
import os
import struct
import errno
import shlex
import ssl
import sys
import urllib.request, urllib.error, urllib.parse

##########From http://stackoverflow.com/questions/600268/mkdir-p-functionality-in-python
def pmkdir(path):
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else: raise

##########From http://stackoverflow.com/questions/377017/test-if-executable-exists-in-python/377028#377028
def which(program):
    import os
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)
    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file
    return None

##########Based on https://stackoverflow.com/questions/5783517/downloading-progress-bar-urllib2-python
def report_chunk(bytes_so_far, chunk_size, total_size):
    percent = float(bytes_so_far) / total_size
    percent = round(percent*100, 2)
    sys.stdout.write('\rDownloaded and decrypted %d of %d bytes (%0.2f%%)' % (bytes_so_far, total_size, percent))
    sys.stdout.flush()
    if bytes_so_far >= total_size:
        print('\n')

# download in 0x200000 byte chunks, decrypt the chunk with IVs described below, then write the decrypted chunk to disk (half the file size of decrypting separately!)
def read_chunk(response, outfname, intitle_key, first_iv, chunk_size=0x200000, report_hook=None):
    file_handler = open(outfname,'wb')
    total_size = int(response.getheader('Content-Length'))
    total_size = int(total_size)
    bytes_so_far = 0
    data = []
    first_read_chunk = 0
    while 1:
        if report_hook:
            report_hook(bytes_so_far, chunk_size, total_size)
        chunk = response.read(chunk_size)
        bytes_so_far += len(chunk)
        if not chunk:
             break
        # IV of first chunk should be the Content ID + 28 0s like with the entire file, but each subsequent chunk should be the last 16 bytes of the previous still ciphered chunk
        if first_read_chunk == 0:
            decryptor = AES.new(intitle_key, AES.MODE_CBC, unhexlify(first_iv))
            first_read_chunk = 1
        else:
            decryptor = AES.new(intitle_key, AES.MODE_CBC, prev_chunk[(0x200000 - 16):0x200000])
        dec_chunk = decryptor.decrypt(chunk)
        prev_chunk = chunk
        file_handler.write(dec_chunk)
    file_handler.close()

def system_usage():
    print('Usage: python3 PlaiCDN.py <title_id title_key [-redown -no3ds -nocia] or [-check]> or <title_id [-info]> or [-deckey] or [-checkbin -checkall]')
    print('-info     : used with just a title id to retrieve info from CDN')
    print('-deckey   : print keys from decTitleKeys.bin')
    print('-check    : checks if title id matches key')
    print('-checkbin : checks title keys from decTitleKeys.bin (games only)')
    print('-checkall : use with -checkbin, checks for all titles')
    print('-redown   : redownload content')
    print('-no3ds    : don\'t build 3DS file')
    print('-nocia    : don\'t build CIA file')
    raise SystemExit(0)

def getTitleInfo(title_id):
    tid_high = ((hexlify(title_id)).decode()).upper()[:8]
    tid_index = ['00040010', '0004001B', '000400DB', '0004009B',
                 '0004009B', '00040138', '00040130', '00040001',
                 '00048005', '0004800F', '00040002', '0004008C']
    res_index = ['-System Application-', '-System Data Archive-', '-System Data Archive-', '-System Data Archive-',
                 '-System Applet-', '-System Module-', '-System Module-', '-System Firmware-',
                 '-Download Play Title-', '-TWL System Application-', '-TWL System Data Archive-',
                 '-Game Demo-', '-Addon DLC-']
    if tid_high in tid_index:
        return(res_index[tid_index.index(tid_high)], '---', '-------', '------', '', '---', '---')
        title_name_stripped, region, product_code, publisher, crypto_seed, curr_version, title_size

    # create new SSL context to load decrypted CLCert-A off directory, key and cert are in PEM format
    # see https://github.com/SciresM/ccrypt
    ctrcontext = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
    ctrcontext.load_cert_chain('ctr-common-1.crt', keyfile='ctr-common-1.key')

    # ninja handles handles actions that require authentication, in addition to converting title ID to internal the CDN content ID
    ninjurl = 'https://ninja.ctr.shop.nintendo.net/ninja/ws/titles/id_pair'
    ecurl = 'https://ninja.ctr.shop.nintendo.net/ninja/ws/'

    # use GET request with parameter "title_id[]=mytitle_id" with SSL context to retrieve XML response
    try:
        shopRequest = urllib.request.Request(ninjurl + '?title_id[]=' + (hexlify(title_id)).decode())
        shopRequest.get_method = lambda: 'GET'
        response = urllib.request.urlopen(shopRequest, context=ctrcontext)
        xmlResponse = minidom.parseString((response.read()).decode('UTF-8', 'replace'))
    except urllib.error.URLError as e:
        raise

    # set ns_uid (the internal content ID) to field from XML
    ns_uid = xmlResponse.getElementsByTagName('ns_uid')[0].childNodes[0].data

    # samurai handles metadata actions, including getting a title's info
    # URL regions are by country instead of geographical regions... for some reason
    samuraiurl = 'https://samurai.ctr.shop.nintendo.net/samurai/ws/'
    regionarray = ['JP', 'US', 'GB', 'DE', 'FR', 'ES', 'NL', 'IT', 'HK', 'TW', 'KR']
    eurarray = ['GB', 'DE', 'FR', 'ES', 'NL', 'IT']
    region = ''

    # try loop to figure out which region the title is from; there is no easy way to do this other than try them all
    for i in range(len(regionarray)):
        try:
            country_code = regionarray[i]
            titleRequest = urllib.request.Request(samuraiurl + country_code + '/title/' + ns_uid)
            titleResponse = urllib.request.urlopen(titleRequest, context=ctrcontext)
            ecRequest = urllib.request.Request(ecurl + country_code + '/title/' + ns_uid + '/ec_info')
            ecResponse = urllib.request.urlopen(ecRequest, context=ctrcontext)
        except urllib.error.URLError as e:
            pass
        else:
            if ('JP') in country_code:
                region = region + 'JPN'
            if ('US') in country_code:
                region = region + 'USA'
            if ('TW') in country_code:
                region = region + 'TWN'
            if ('HK') in country_code:
                region = region + 'HKG'
            if ('KR') in country_code:
                region = region + 'KOR'
            if country_code in eurarray:
                region = region + 'EUR'
    if region == '':
        raise
    if len(region) > 3:
        region = 'ALL'

    # get info from the returned XMs from the URL
    xmlResponse = minidom.parseString((titleResponse.read()).decode('UTF-8'))
    title_name = xmlResponse.getElementsByTagName('name')[0].childNodes[0].data
    title_name_stripped = title_name.replace('\n', ' ')
    publisher = xmlResponse.getElementsByTagName('name')[2].childNodes[0].data
    product_code = xmlResponse.getElementsByTagName('product_code')[0].childNodes[0].data

    xmlResponse = minidom.parseString((ecResponse.read()).decode('UTF-8'))
    curr_version = xmlResponse.getElementsByTagName('title_version')[0].childNodes[0].data
    title_size = '{:.5}'.format(int(xmlResponse.getElementsByTagName('content_size')[0].childNodes[0].data) / 1000000)

    try:
        crypto_seed = xmlResponse.getElementsByTagName('external_seed')[0].childNodes[0].data
    except:
        crypto_seed = ''

    # some windows unicode character bullshit
    if 'Windows' in platform.system():
        title_name_stripped = ''.join([i if ord(i) < 128 else ' ' for i in title_name_stripped])
        publisher = ''.join([i if ord(i) < 128 else ' ' for i in publisher])

    return(title_name_stripped, region, product_code, publisher, crypto_seed, curr_version, title_size)

#from https://github.com/Relys/3DS_Multi_Decryptor/blob/master/ticket-title_key_stuff/printKeys.py
for i in range(len(sys.argv)):
    if sys.argv[i] == '-deckey':
        with open('decTitleKeys.bin', 'rb') as file_handler:
            nEntries = os.fstat(file_handler.fileno()).st_size / 32
            file_handler.seek(16, os.SEEK_SET)
            for i in range(int(nEntries)):
                file_handler.seek(8, os.SEEK_CUR)
                title_id = file_handler.read(8)
                decryptedTitleKey = file_handler.read(16)
                print('%s: %s' % ((hexlify(title_id)).decode(), (hexlify(decryptedTitleKey)).decode()))
        raise SystemExit(0)

for i in range(len(sys.argv)):
    if sys.argv[i] == '-info':
        title_id = sys.argv[1]
        if len(title_id) != 16:
            print('Invalid arguments')
            raise SystemExit(0)

        if (not os.path.isfile('ctr-common-1.crt')) or (not os.path.isfile('ctr-common-1.crt')):
                print('\nCould not find certificate files, all secure connections will fail!\n')

        base_url = 'http://ccs.cdn.c.shop.nintendowifi.net/ccs/download/' + title_id
        # download tmd_var and set to object
        try:
            tmd_var = urllib.request.urlopen(base_url + '/tmd')
        except urllib.error.URLError as e:
            print('Could not retrieve tmd; received error: ' + str(e))
            continue
        tmd_var = tmd_var.read()

        content_count = unpack('>H', tmd_var[0x206:0x208])[0]
        for i in range(content_count):
            cOffs = 0xB04+(0x30*i)
            cID = format(unpack('>I', tmd_var[cOffs:cOffs+4])[0], '08x')
            cIDX = format(unpack('>H', tmd_var[cOffs+4:cOffs+6])[0], '04x')
            cSIZE = format(unpack('>Q', tmd_var[cOffs+8:cOffs+16])[0], 'd')
            cHASH = tmd_var[cOffs+16:cOffs+48]
            # If content count above 8 (not a normal application), don't make 3ds
            if unpack('>H', tmd_var[cOffs+4:cOffs+6])[0] >= 8:
                make_3ds = 0
            print('\n')
            print('Content ID:    ' + cID)
            print('Content Index: ' + cIDX)
            print('Content Size:  ' + cSIZE)
            print('Content Hash:  ' + (hexlify(cHASH)).decode())
        try:
            ret_title_name_stripped, ret_region, ret_product_code, ret_publisher, ret_crypto_seed, ret_curr_version, ret_title_size = getTitleInfo((unhexlify(title_id)))
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            print('\nCould not retrieve CDN data!\n')
            ret_region = '---'
            ret_title_name_stripped = '---Unknown---'
            ret_product_code = '------'
            ret_publisher = '------'
            ret_crypto_seed = ''
            ret_curr_version = '---'
            ret_title_size = '---'

        print('\n~\n')

        print('Title Name: ' + ret_title_name_stripped)
        print('Region: ' + ret_region)
        print('Product Code: ' + ret_product_code)
        print('Publisher: ' + ret_publisher)
        print('Current Version: ' + ret_curr_version)
        if ret_title_size == '---':
            print('Title Size: ' + ret_title_size)
        else:
            print('Title Size: ' + ret_title_size + 'mb')
        if ret_crypto_seed != '':
            print('9.6 Crypto Seed: ' + ret_crypto_seed)
        print('\n')
        raise SystemExit(0)

for i in range(len(sys.argv)):
    if sys.argv[i] == '-checkbin':
        if (not os.path.isfile('ctr-common-1.crt')) or (not os.path.isfile('ctr-common-1.crt')):
            print('\nCould not find certificate files, all secure connections will fail!')
        checkAll = 0
        for i in range(len(sys.argv)):
            if sys.argv[i] == '-checkall': checkAll = 1
        with open('decTitleKeys.bin', 'rb') as file_handler:
            nEntries = os.fstat(file_handler.fileno()).st_size / 32
            file_handler.seek(16, os.SEEK_SET)
            final_output = []
            print('\n')
            # format: Title Name (left aligned) gets 40 characters, Title ID (Right aligned) gets 16, Titlekey (Right aligned) gets 32, and Region (Right aligned) gets 3
            # anything longer is truncated, anything shorter is padded
            print("{0:<40} {1:>16} {2:>32} {3:>3}".format('Name', 'Title ID', 'Titlekey', 'Region'))
            print("-"*100)
            for i in range(int(nEntries)):
                file_handler.seek(8, os.SEEK_CUR)
                title_id = file_handler.read(8)
                decryptedTitleKey = file_handler.read(16)
                # regular CDN URL for downloads off the CDN
                base_url = 'http://ccs.cdn.c.shop.nintendowifi.net/ccs/download/' + (hexlify(title_id)).decode()
                if checkAll == 0 and ((hexlify(title_id)).decode()).upper()[:8] != '00040000':
                    continue
                # download tmd_var and set to object
                try:
                    tmd_var = urllib.request.urlopen(base_url + '/tmd')
                except urllib.error.URLError as e:
                    continue
                tmd_var = tmd_var.read()
                # try to get info from the CDN, if it fails then set title and region to unknown
                try:
                    ret_title_name_stripped, ret_region, ret_product_code, ret_publisher, ret_crypto_seed, ret_curr_version, ret_title_size = getTitleInfo(title_id)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except:
                    print('\nCould not retrieve CDN data!\n')
                    ret_region = '---'
                    ret_title_name_stripped = '---Unknown---'
                    ret_product_code = '------'
                    ret_publisher = '------'
                    ret_crypto_seed = ''
                    ret_curr_version = '---'
                    ret_title_size = '---'

                content_count = unpack('>H', tmd_var[0x206:0x208])[0]
                for i in range(content_count):
                    cOffs = 0xB04+(0x30*i)
                    cID = format(unpack('>I', tmd_var[cOffs:cOffs+4])[0], '08x')
                    # use range requests to download bytes 0 through 271, needed 272 instead of 260 because AES-128-CBC encrypts in chunks of 128 bits
                    try:
                        checkReq = urllib.request.Request('%s/%s'%(base_url, cID))
                        checkReq.headers['Range'] = 'bytes=%s-%s' % (0, 271)
                        checkTemp = urllib.request.urlopen(checkReq)
                    except urllib.error.URLError as e:
                        continue
                # set IV to offset 0xf0 length 0x10 of ciphertext; thanks to yellows8 for the offset
                checkTempPerm = checkTemp.read()
                checkIv = checkTempPerm[0xf0:0x100]
                decryptor = AES.new(decryptedTitleKey, AES.MODE_CBC, checkIv)
                # check for magic ('NCCH') at offset 0x100 length 0x104 of the decrypted content
                checkTempOut = decryptor.decrypt(checkTempPerm)[0x100:0x104]
                if 'NCCH' in checkTempOut.decode('UTF-8', 'ignore'):
                    # format: Title Name (left aligned) gets 40 characters, Title ID (Right aligned) gets 16, Titlekey (Right aligned) gets 32, and Region (Right aligned) gets 3
                    # anything longer is truncated, anything shorter is padded
                    print("{0:<40.40} {1:>16} {2:>32} {3:>3}".format(ret_title_name_stripped, (hexlify(title_id).decode()).strip(), ((hexlify(decryptedTitleKey)).decode()).strip(), ret_region))
            raise SystemExit(0)

#if args for deckeys or checkbin weren't used above, remaining functions require 3 args minimum
if len(sys.argv) < 3:
    system_usage()

# default values
title_id = sys.argv[1]
title_key = sys.argv[2]
force_download = 0
make_3ds = 1
make_cia = 1
checkKey = 0
checkTempOut = None

# check args
for i in range(len(sys.argv)):
    if sys.argv[i] == '-redown': force_download = 1
    elif sys.argv[i] == '-no3ds': make_3ds = 0
    elif sys.argv[i] == '-nocia': make_cia = 0
    elif sys.argv[i] == '-check': checkKey = 1

if len(title_key) != 32 or len(title_id) != 16:
    print('Invalid arguments')
    raise SystemExit(0)

# set CDN default URL
base_url = 'http://ccs.cdn.c.shop.nintendowifi.net/ccs/download/' + title_id

# download tmd and set to 'tmd_var' object
try:
    tmd_var = urllib.request.urlopen(base_url + '/tmd')
except urllib.error.URLError as e:
    print('ERROR: Bad title ID?')
    raise SystemExit(0)
tmd_var = tmd_var.read()

#create folder
pmkdir(title_id)

# https://www.3dbrew.org/wiki/Title_metadata#Signature_Data
if bytes('\x00\x01\x00\x04', 'UTF-8') not in tmd_var[:4]:
    print('Unexpected signature type.')
    raise SystemExit(0)

# If not normal application, don't make 3ds
if title_id[:8] != '00040000':
    make_3ds = 0

# Check OS, path, and current dir to set makerom location
if 'Windows' in platform.system():
    if os.path.isfile('makerom.exe'):
        makerom_command = 'makerom.exe'
    else:
        makerom_command = which('makerom.exe')
else:
    if os.path.isfile('makerom'):
        makerom_command = './makerom'
    else:
        makerom_command = which('makerom')
if makerom_command == None:
    print('Could not find makerom!')
    raise SystemExit(0)

# Set proper common key ID
if unpack('>H', tmd_var[0x18e:0x190])[0] & 0x10 == 0x10:
    ckeyid = 1
else:
    ckeyid = 0

# Set Proper Version
title_version = unpack('>H', tmd_var[0x1dc:0x1de])[0]

# Set Save Size
save_size = (unpack('<I', tmd_var[0x19a:0x19e])[0])/1024

# If DLC Set DLC flag
dlcflag = ''
if '0004008c' in title_id:
    dlcflag = '-dlc'
content_count = unpack('>H', tmd_var[0x206:0x208])[0]

# If content count above 8 (not a normal application), don't make 3ds
if content_count > 8:
    make_3ds = 0
command_cID = []

# Download Contents
fSize = 16384
for i in range(content_count):
    cOffs = 0xB04+(0x30*i)
    cID = format(unpack('>I', tmd_var[cOffs:cOffs+4])[0], '08x')
    cIDX = format(unpack('>H', tmd_var[cOffs+4:cOffs+6])[0], '04x')
    cSIZE = format(unpack('>Q', tmd_var[cOffs+8:cOffs+16])[0], 'd')
    cHASH = tmd_var[cOffs+16:cOffs+48]
    # If content count above 8 (not a normal application), don't make 3ds
    if unpack('>H', tmd_var[cOffs+4:cOffs+6])[0] >= 8:
        make_3ds = 0
    print('Content ID:    ' + cID)
    print('Content Index: ' + cIDX)
    print('Content Size:  ' + cSIZE)
    print('Content Hash:  ' + (hexlify(cHASH)).decode())
    # set output location to a folder named for title id and contentid.dec as the file
    outfname = title_id + '/' + cID + '.dec'
    if checkKey == 1:
        if (not os.path.isfile('ctr-common-1.crt')) or (not os.path.isfile('ctr-common-1.crt')):
            print('\nCould not find certificate files, all secure connections will fail!')
        print('\nDownloading and decrypting the first 272 bytes of ' + cID + ' for key check\n')
        # use range requests to download bytes 0 through 271, needed 272 instead of 260 because AES-128-CBC encrypts in chunks of 128 bits
        try:
            checkReq = urllib.request.Request('%s/%s'%(base_url, cID))
            checkReq.headers['Range'] = 'bytes=%s-%s' % (0, 271)
            checkTemp = urllib.request.urlopen(checkReq)
        except urllib.error.URLError as e:
            print('ERROR: Possibly wrong container?\n')
            raise SystemExit(0)
        try:
            ret_title_name_stripped, ret_region, ret_product_code, ret_publisher, ret_crypto_seed, ret_curr_version, ret_title_size = getTitleInfo((unhexlify(title_id)))
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            print('\nCould not retrieve CDN data!\n')
            ret_region = '---'
            ret_title_name_stripped = '---Unknown---'
            ret_product_code = '------'
            ret_publisher = '------'
            ret_crypto_seed = ''
            ret_curr_version = '---'
            ret_title_size = '---'
        # set IV to offset 0xf0 length 0x10 of ciphertext; thanks to yellows8 for the offset
        checkTempPerm = checkTemp.read()
        decryptor = AES.new(unhexlify(title_key), AES.MODE_CBC, checkTempPerm[0xf0:0x100])
        # check for magic ('NCCH') at offset 0x100 length 0x104 of the decrypted content
        checkTempOut = decryptor.decrypt(checkTempPerm)[0x100:0x104]
        print('Title Name: ' + ret_title_name_stripped)
        print('Region: ' + ret_region)
        print('Product Code: ' + ret_product_code)
        print('Publisher: ' + ret_publisher)
        print('Current Version: ' + ret_curr_version)
        print('Title Size: ' + ret_title_size + 'mb')
        if ret_crypto_seed != '':
            print('9.6 Crypto Seed: ' + ret_crypto_seed)
        print('\n')
        if 'NCCH' not in checkTempOut.decode('UTF-8', 'ignore'):
            print('\nERROR: Decryption failed; invalid titlekey?')
            raise SystemExit(0)
        print('\nTitlekey successfully verified to match title ID ' + title_id)
        raise SystemExit(0)
    # if the content location does not exist, redown is set, or the size is incorrect redownload
    if os.path.exists(outfname) == 0 or force_download == 1 or os.path.getsize(outfname) != unpack('>Q', tmd_var[cOffs+8:cOffs+16])[0]:
        response = urllib.request.urlopen(base_url + '/' + cID)
        read_chunk(response, outfname, unhexlify(title_key), cIDX + '0000000000000000000000000000', report_hook=report_chunk)
    # check hash and NCCH of downloaded content
    with open(outfname,'rb') as file_handler:
        file_handler.seek(0, os.SEEK_END)
        file_handlerSize = file_handler.tell()
        if file_handler.tell() != unpack('>Q', tmd_var[cOffs+8:cOffs+16])[0]:
            print('Title size mismatch.  Download likely incomplete')
            print('Downloaded: ' + format(file_handler.tell(), 'd'))
            raise SystemExit(0)
        file_handler.seek(0)
        hash = sha256()
        while file_handler.tell() != file_handlerSize:
            hash.update(file_handler.read(0x1000000))
            print('Checking Hash: ' + format(float(file_handler.tell()*100)/file_handlerSize,'.1f') + '% done\r', end=' ')
        sha256file = hash.hexdigest()
        if sha256file != (hexlify(cHASH)).decode():
            print('hash mismatched, Decryption likely failed, wrong key or file modified?')
            print('got hash: ' + sha256file)
            raise SystemExit(0)
        print('Hash verified successfully.')
        file_handler.seek(0x100)
        if (file_handler.read(4)).decode('UTF-8', 'ignore') != 'NCCH':
            make_cia = 0
            make_3ds = 0
            file_handler.seek(0x60)
            if file_handler.read(4) != 'WfA\0':
                print('Not NCCH, nor DSiWare, file likely corrupted')
                raise SystemExit(0)
            else:
                print('Not an NCCH container, likely DSiWare')
        file_handler.seek(0, os.SEEK_END)
        fSize += file_handler.tell()
    print('\n')
    command_cID = command_cID + ['-i', outfname + ':0x' + cIDX + ':0x' + cID]

print('\n')
print('The NCCH on eShop games is encrypted and cannot be used')
print('without decryption on a 3DS. To fix this you should copy')
print('all .dec files in the Title ID folder to \'/D9Game/\'')
print('on your SD card, then use the following option in Decrypt9:')
print('\n')
print('\'Game Decryptor Options\' > \'NCCH/NCSD Decryptor\'')
print('\n')
print('Once you have decrypted the files, copy the .dec files from')
print('\'/D9Game/\' back into the Title ID folder, overwriting them.')
print('\n')
input('Press Enter once you have done this...')

# create the RSF File
rom_rsf = 'Option:\n  MediaFootPadding: true\n  EnableCrypt: false\nSystemControlInfo:\n  SaveDataSize: $(SaveSize)K'
with open('rom.rsf', 'wb') as file_handler:
    file_handler.write(rom_rsf.encode())

# set makerom command with subproces, removing '' if dlcflag isn't set (otherwise makerom breaks)
dotcia_command_array = ([makerom_command, '-f', 'cia', '-rsf', 'rom.rsf', '-o', title_id + '.cia', '-ckeyid', str(ckeyid), '-major', str((title_version & 0xfc00) >> 10), '-minor', str((title_version & 0x3f0) >> 4), '-micro', str(title_version & 0xF), '-DSaveSize=' + str(save_size), str(dlcflag)] + command_cID)
dot3ds_command_array = ([makerom_command, '-f', 'cci', '-rsf', 'rom.rsf', '-nomodtid', '-o', title_id + '.3ds', '-ckeyid', str(ckeyid), '-major', str((title_version & 0xfc00) >> 10), '-minor', str((title_version & 0x3f0) >> 4), '-micro', str(title_version & 0xF), '-DSaveSize=' + str(save_size), str(dlcflag)] + command_cID)

if '' in dotcia_command_array:
    dotcia_command_array.remove('')
if '' in dot3ds_command_array:
    dot3ds_command_array.remove('')

if make_cia == 1:
    print('\nBuilding ' + title_id + '.cia...')
    call(dotcia_command_array, stderr=STDOUT)

if make_3ds == 1:
    print('\nBuilding ' + title_id + '.3ds...')
    call(dot3ds_command_array, stderr=STDOUT)

if os.path.isfile('rom.rsf'):
    os.remove('rom.rsf')

if make_cia == 1 and not os.path.isfile(title_id + '.cia'):
    print('Something went wrong.')
    raise SystemExit(0)

if make_3ds == 1 and not os.path.isfile(title_id + '.3ds'):
    print('Something went wrong.')
    raise SystemExit(0)

print('Done!')
