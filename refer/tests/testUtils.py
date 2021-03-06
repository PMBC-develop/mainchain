import copy
import decimal
import subprocess
import time
import glob
import shutil
import os
import platform
from collections import namedtuple
import re
import string
import signal
import datetime
import inspect
import sys
import random
import json
import shlex

from core_symbol import CORE_SYMBOL

###########################################################################################
class Utils:
    Debug=False
    FNull = open(os.devnull, 'w')

    ClientPath="programs/cl/cl"

    WalletName="kd"
    WalletPath="programs/kd/"+ WalletName

    ServerName="nod"
    ServerPath="programs/nod/"+ ServerName

    LauncherPath="programs/io-launcher/io-launcher"
    MongoPath="mongo"

    @staticmethod
    def Print(*args, **kwargs):
        stackDepth=len(inspect.stack())-2
        s=' '*stackDepth
        sys.stdout.write(s)
        print(*args, **kwargs)

    SyncStrategy=namedtuple("ChainSyncStrategy", "name id arg")

    SyncNoneTag="none"
    SyncReplayTag="replay"
    SyncResyncTag="resync"

    SigKillTag="kill"
    SigTermTag="term"

    systemWaitTimeout=90

    # mongoSyncTime: nod mongodb plugin seems to sync with a 10-15 seconds delay. This will inject
    #  a wait period before the 2nd DB check (if first check fails)
    mongoSyncTime=25

    @staticmethod
    def setMongoSyncTime(syncTime):
        Utils.mongoSyncTime=syncTime

    @staticmethod
    def setSystemWaitTimeout(timeout):
        Utils.systemWaitTimeout=timeout

    @staticmethod
    def getChainStrategies():
        chainSyncStrategies={}

        chainSyncStrategy=Utils.SyncStrategy(Utils.SyncNoneTag, 0, "")
        chainSyncStrategies[chainSyncStrategy.name]=chainSyncStrategy

        chainSyncStrategy=Utils.SyncStrategy(Utils.SyncReplayTag, 1, "--replay-blockchain")
        chainSyncStrategies[chainSyncStrategy.name]=chainSyncStrategy

        chainSyncStrategy=Utils.SyncStrategy(Utils.SyncResyncTag, 2, "--delete-all-blocks")
        chainSyncStrategies[chainSyncStrategy.name]=chainSyncStrategy

        return chainSyncStrategies

    @staticmethod
    def checkOutput(cmd):
        assert(isinstance(cmd, list))
        #retStr=subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode("utf-8")
        retStr=subprocess.check_output(cmd).decode("utf-8")
        return retStr

    @staticmethod
    def errorExit(msg="", raw=False, errorCode=1):
        Utils.Print("ERROR:" if not raw else "", msg)
        exit(errorCode)

    @staticmethod
    def waitForObj(lam, timeout=None):
        if timeout is None:
            timeout=60

        endTime=time.time()+timeout
        while endTime > time.time():
            ret=lam()
            if ret is not None:
                return ret
            sleepTime=3
            Utils.Print("cmd: sleep %d seconds, remaining time: %d seconds" %
                        (sleepTime, endTime - time.time()))
            time.sleep(sleepTime)

        return None

    @staticmethod
    def waitForBool(lam, timeout=None):
        myLam = lambda: True if lam() else None
        ret=Utils.waitForObj(myLam, timeout)
        return False if ret is None else ret


###########################################################################################
class Account(object):
    # pylint: disable=too-few-public-methods

    def __init__(self, name):
        self.name=name

        self.ownerPrivateKey=None
        self.ownerPublicKey=None
        self.activePrivateKey=None
        self.activePublicKey=None


    def __str__(self):
        return "Name: %s" % (self.name)

###########################################################################################
# pylint: disable=too-many-public-methods
class Node(object):

    # pylint: disable=too-many-instance-attributes
    # pylint: disable=too-many-arguments
    def __init__(self, host, port, pid=None, cmd=None, enableMongo=False, mongoHost="localhost", mongoPort=27017, mongoDb="test"):
        self.host=host
        self.port=port
        self.pid=pid
        self.cmd=cmd
        self.killed=False # marks node as killed
        self.enableMongo=enableMongo
        self.mongoSyncTime=None if Utils.mongoSyncTime < 1 else Utils.mongoSyncTime
        self.mongoHost=mongoHost
        self.mongoPort=mongoPort
        self.mongoDb=mongoDb
        self.endpointArgs="--url http://%s:%d" % (self.host, self.port)
        self.mongoEndpointArgs=""
        if self.enableMongo:
            self.mongoEndpointArgs += "--host %s --port %d %s" % (mongoHost, mongoPort, mongoDb)

    def __str__(self):
        #return "Host: %s, Port:%d, Pid:%s, Cmd:\"%s\"" % (self.host, self.port, self.pid, self.cmd)
        return "Host: %s, Port:%d" % (self.host, self.port)

    @staticmethod
    def validateTransaction(trans):
        assert trans
        assert isinstance(trans, dict), print("Input type is %s" % type(trans))

        def printTrans(trans):
            Utils.Print("ERROR: Failure in transaction validation.")
            Utils.Print("Transaction: %s" % (json.dumps(trans, indent=1)))

        assert trans["processed"]["receipt"]["status"] == "executed", printTrans(trans)

    @staticmethod
    def runCmdReturnJson(cmd, trace=False):
        cmdArr=shlex.split(cmd)
        retStr=Utils.checkOutput(cmdArr)
        jStr=Node.filterJsonObject(retStr)
        if trace: Utils.Print ("RAW > %s"% (retStr))
        if trace: Utils.Print ("JSON> %s"% (jStr))
        if not jStr:
            msg="Expected JSON response"
            Utils.Print ("ERROR: "+ msg)
            Utils.Print ("RAW > %s"% retStr)
            raise TypeError(msg)

        try:
            jsonData=json.loads(jStr)
            return jsonData
        except json.decoder.JSONDecodeError as ex:
            Utils.Print (ex)
            Utils.Print ("RAW > %s"% retStr)
            Utils.Print ("JSON> %s"% jStr)
            raise

    @staticmethod
    def __runCmdArrReturnJson(cmdArr, trace=False):
        retStr=Utils.checkOutput(cmdArr)
        jStr=Node.filterJsonObject(retStr)
        if trace: Utils.Print ("RAW > %s"% (retStr))
        if trace: Utils.Print ("JSON> %s"% (jStr))
        jsonData=json.loads(jStr)
        return jsonData

    @staticmethod
    def runCmdReturnStr(cmd, trace=False):
        retStr=Node.__checkOutput(cmd.split())
        if trace: Utils.Print ("RAW > %s"% (retStr))
        return retStr

    @staticmethod
    def filterJsonObject(data):
        firstIdx=data.find('{')
        lastIdx=data.rfind('}')
        retStr=data[firstIdx:lastIdx+1]
        return retStr

    @staticmethod
    def __checkOutput(cmd):
        retStr=subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode("utf-8")
        #retStr=subprocess.check_output(cmd).decode("utf-8")
        return retStr

    # Passes input to stdin, executes cmd. Returns tuple with return code(int),
    #  stdout(byte stream) and stderr(byte stream).
    @staticmethod
    def stdinAndCheckOutput(cmd, subcommand):
        outs=None
        errs=None
        ret=0
        try:
            popen=subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            outs,errs=popen.communicate(input=subcommand.encode("utf-8"))
            ret=popen.wait()
        except subprocess.CalledProcessError as ex:
            msg=ex.output
            return (ex.returncode, msg, None)

        return (ret, outs, errs)

    @staticmethod
    def normalizeJsonObject(extJStr):
        tmpStr=extJStr
        tmpStr=re.sub(r'ObjectId\("(\w+)"\)', r'"ObjectId-\1"', tmpStr)
        tmpStr=re.sub(r'ISODate\("([\w|\-|\:|\.]+)"\)', r'"ISODate-\1"', tmpStr)
        return tmpStr

    @staticmethod
    def runMongoCmdReturnJson(cmdArr, subcommand, trace=False):
        retId,outs=Node.stdinAndCheckOutput(cmdArr, subcommand)
        if retId is not 0:
            return None
        outStr=Node.byteArrToStr(outs)
        if not outStr:
            return None
        extJStr=Node.filterJsonObject(outStr)
        if not extJStr:
            return None
        jStr=Node.normalizeJsonObject(extJStr)
        if not jStr:
            return None
        if trace: Utils.Print ("RAW > %s"% (outStr))
        #trace and Utils.Print ("JSON> %s"% jStr)
        jsonData=json.loads(jStr)
        return jsonData

    @staticmethod
    def getTransId(trans):
        """Retrieve transaction id from dictionary object."""
        assert trans
        assert isinstance(trans, dict), print("Input type is %s" % type(trans))

        #Utils.Print("%s" % trans)
        transId=trans["transaction_id"]
        return transId

    @staticmethod
    def byteArrToStr(arr):
        return arr.decode("utf-8")

    def setWalletEndpointArgs(self, args):
        self.endpointArgs="--url http://%s:%d %s" % (self.host, self.port, args)

    def validateAccounts(self, accounts):
        assert(accounts)
        assert(isinstance(accounts, list))

        for account in accounts:
            assert(account)
            assert(isinstance(account, Account))
            if Utils.Debug: Utils.Print("Validating account %s" % (account.name))
            accountInfo=self.getAccount(account.name)
            try:
                assert(accountInfo)
                assert(accountInfo["account_name"] == account.name)
            except (AssertionError, TypeError, KeyError) as _:
                Utils.Print("account validation failed. account: %s" % (account.name))
                raise

    # pylint: disable=too-many-branches
    def getBlock(self, blockNum, retry=True, silentErrors=False):
        """Given a blockId will return block details."""
        assert(isinstance(blockNum, str))
        if not self.enableMongo:
            cmd="%s %s get block %s" % (Utils.ClientPath, self.endpointArgs, blockNum)
            if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
            try:
                trans=Node.runCmdReturnJson(cmd)
                return trans
            except subprocess.CalledProcessError as ex:
                if not silentErrors:
                    msg=ex.output.decode("utf-8")
                    Utils.Print("ERROR: Exception during get block. %s" % (msg))
                return None
        else:
            for _ in range(2):
                cmd="%s %s" % (Utils.MongoPath, self.mongoEndpointArgs)
                subcommand='db.Blocks.findOne( { "block_num": %s } )' % (blockNum)
                if Utils.Debug: Utils.Print("cmd: echo '%s' | %s" % (subcommand, cmd))
                try:
                    trans=Node.runMongoCmdReturnJson(cmd.split(), subcommand)
                    if trans is not None:
                        return trans
                except subprocess.CalledProcessError as ex:
                    if not silentErrors:
                        msg=ex.output.decode("utf-8")
                        Utils.Print("ERROR: Exception during get db node get block. %s" % (msg))
                    return None
                if not retry:
                    break
                if self.mongoSyncTime is not None:
                    if Utils.Debug: Utils.Print("cmd: sleep %d seconds" % (self.mongoSyncTime))
                    time.sleep(self.mongoSyncTime)

        return None

    def getBlockById(self, blockId, retry=True, silentErrors=False):
        for _ in range(2):
            cmd="%s %s" % (Utils.MongoPath, self.mongoEndpointArgs)
            subcommand='db.Blocks.findOne( { "block_id": "%s" } )' % (blockId)
            if Utils.Debug: Utils.Print("cmd: echo '%s' | %s" % (subcommand, cmd))
            try:
                trans=Node.runMongoCmdReturnJson(cmd.split(), subcommand)
                if trans is not None:
                    return trans
            except subprocess.CalledProcessError as ex:
                if not silentErrors:
                    msg=ex.output.decode("utf-8")
                    Utils.Print("ERROR: Exception during db get block by id. %s" % (msg))
                return None
            if not retry:
                break
            if self.mongoSyncTime is not None:
                if Utils.Debug: Utils.Print("cmd: sleep %d seconds" % (self.mongoSyncTime))
                time.sleep(self.mongoSyncTime)

        return None

    def doesNodeHaveBlockNum(self, blockNum):
        assert isinstance(blockNum, int)
        assert (blockNum > 0)

        info=self.getInfo(silentErrors=True)
        assert(info)
        last_irreversible_block_num=0
        try:
            last_irreversible_block_num=int(info["last_irreversible_block_num"])
        except (TypeError, KeyError) as _:
            Utils.Print("Failure in get info parsing. %s" % (info))
            raise

        return True if blockNum <= last_irreversible_block_num else True

    # pylint: disable=too-many-branches
    def getTransaction(self, transId, retry=True, silentErrors=False):
        if not self.enableMongo:
            cmd="%s %s get transaction %s" % (Utils.ClientPath, self.endpointArgs, transId)
            if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
            try:
                trans=Node.runCmdReturnJson(cmd)
                return trans
            except subprocess.CalledProcessError as ex:
                msg=ex.output.decode("utf-8")
                if "Failed to connect" in msg:
                    Utils.Print("ERROR: Node is unreachable. %s" % (msg))
                    raise
                if not silentErrors:
                    Utils.Print("ERROR: Exception during transaction retrieval. %s" % (msg))
                return None
        else:
            for _ in range(2):
                cmd="%s %s" % (Utils.MongoPath, self.mongoEndpointArgs)
                subcommand='db.Transactions.findOne( { $and : [ { "transaction_id": "%s" }, {"pending":false} ] } )' % (transId)
                if Utils.Debug: Utils.Print("cmd: echo '%s' | %s" % (subcommand, cmd))
                try:
                    trans=Node.runMongoCmdReturnJson(cmd.split(), subcommand)
                    return trans
                except subprocess.CalledProcessError as ex:
                    if not silentErrors:
                        msg=ex.output.decode("utf-8")
                        Utils.Print("ERROR: Exception during get db node get trans. %s" % (msg))
                    return None
                if not retry:
                    break
                if self.mongoSyncTime is not None:
                    if Utils.Debug: Utils.Print("cmd: sleep %d seconds" % (self.mongoSyncTime))
                    time.sleep(self.mongoSyncTime)

        return None

    def isTransInBlock(self, transId, blockId):
        """Check if transId is within block identified by blockId"""
        assert(transId)
        assert(isinstance(transId, str))
        assert(blockId)
        assert(isinstance(blockId, str))

        block=self.getBlock(blockId)
        transactions=None
        try:
            transactions=block["transactions"]
        except (AssertionError, TypeError, KeyError) as _:
            Utils.Print("Failed to parse block. %s" % (block))
            raise

        if transactions is not None:
            for trans in transactions:
                assert(trans)
                try:
                    myTransId=trans["trx"]["id"]
                    if transId == myTransId:
                        return True
                except (TypeError, KeyError) as _:
                    Utils.Print("Failed to parse block transactions. %s" % (trans))

        return False

    def getBlockIdByTransId(self, transId):
        """Given a transaction Id (string), will return block id (string) containing the transaction"""
        assert(transId)
        assert(isinstance(transId, str))
        trans=self.getTransaction(transId)
        assert(trans)

        refBlockNum=None
        try:
            refBlockNum=trans["trx"]["trx"]["ref_block_num"]
            refBlockNum=int(refBlockNum)+1
        except (TypeError, ValueError, KeyError) as _:
            Utils.Print("transaction parsing failed. Transaction: %s" % (trans))
            raise

        headBlockNum=self.getHeadBlockNum()
        assert(headBlockNum)
        try:
            headBlockNum=int(headBlockNum)
        except(ValueError) as _:
            Utils.Print("Info parsing failed. %s" % (headBlockNum))

        for blockNum in range(refBlockNum, headBlockNum+1):
            if self.isTransInBlock(str(transId), str(blockNum)):
                return str(blockNum)

        return None

    def doesNodeHaveTransId(self, transId):
        """Check if transaction (transId) has been finalized."""
        assert(transId)
        assert(isinstance(transId, str))
        blockId=self.getBlockIdByTransId(transId)
        return True if blockId else None

    # Disabling MongodDB funbction
    # def getTransByBlockId(self, blockId, retry=True, silentErrors=False):
    #     for _ in range(2):
    #         cmd="%s %s" % (Utils.MongoPath, self.mongoEndpointArgs)
    #         subcommand='db.Transactions.find( { "block_id": "%s" } )' % (blockId)
    #         if Utils.Debug: Utils.Print("cmd: echo '%s' | %s" % (subcommand, cmd))
    #         try:
    #             trans=Node.runMongoCmdReturnJson(cmd.split(), subcommand, True)
    #             if trans is not None:
    #                 return trans
    #         except subprocess.CalledProcessError as ex:
    #             if not silentErrors:
    #                 msg=ex.output.decode("utf-8")
    #                 Utils.Print("ERROR: Exception during db get trans by blockId. %s" % (msg))
    #             return None
    #         if not retry:
    #             break
    #         if self.mongoSyncTime is not None:
    #             if Utils.Debug: Utils.Print("cmd: sleep %d seconds" % (self.mongoSyncTime))
    #             time.sleep(self.mongoSyncTime)

    #     return None

    def getActionFromDb(self, transId, retry=True, silentErrors=False):
        for _ in range(2):
            cmd="%s %s" % (Utils.MongoPath, self.mongoEndpointArgs)
            subcommand='db.Actions.findOne( { "transaction_id": "%s" } )' % (transId)
            if Utils.Debug: Utils.Print("cmd: echo '%s' | %s" % (subcommand, cmd))
            try:
                trans=Node.runMongoCmdReturnJson(cmd.split(), subcommand)
                if trans is not None:
                    return trans
            except subprocess.CalledProcessError as ex:
                if not silentErrors:
                    msg=ex.output.decode("utf-8")
                    Utils.Print("ERROR: Exception during get db node get message. %s" % (msg))
                return None
            if not retry:
                break
            if self.mongoSyncTime is not None:
                if Utils.Debug: Utils.Print("cmd: sleep %d seconds" % (self.mongoSyncTime))
                time.sleep(self.mongoSyncTime)

        return None

    def getMessageFromDb(self, transId, retry=True, silentErrors=False):
        for _ in range(2):
            cmd="%s %s" % (Utils.MongoPath, self.mongoEndpointArgs)
            subcommand='db.Messages.findOne( { "transaction_id": "%s" } )' % (transId)
            if Utils.Debug: Utils.Print("cmd: echo '%s' | %s" % (subcommand, cmd))
            try:
                trans=Node.runMongoCmdReturnJson(cmd.split(), subcommand)
                if trans is not None:
                    return trans
            except subprocess.CalledProcessError as ex:
                if not silentErrors:
                    msg=ex.output.decode("utf-8")
                    Utils.Print("ERROR: Exception during get db node get message. %s" % (msg))
                return None
            if not retry:
                break
            if self.mongoSyncTime is not None:
                if Utils.Debug: Utils.Print("cmd: sleep %d seconds" % (self.mongoSyncTime))
                time.sleep(self.mongoSyncTime)

        return None

    # Create & initialize account and return creation transactions. Return transaction json object
    def createInitializeAccount(self, account, creatorAccount, stakedDeposit=1000, waitForTransBlock=False):
        cmd='%s %s system newaccount -j %s %s %s %s --stake-net "100 %s" --stake-cpu "100 %s" --buy-ram- "100 %s"' % (
            Utils.ClientPath, self.endpointArgs, creatorAccount.name, account.name,
            account.ownerPublicKey, account.activePublicKey,
            CORE_SYMBOL, CORE_SYMBOL, CORE_SYMBOL)

        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        trans=None
        try:
            trans=Node.runCmdReturnJson(cmd)
            transId=Node.getTransId(trans)
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            Utils.Print("ERROR: Exception during account creation. %s" % (msg))
            return None

        if stakedDeposit > 0:
            self.waitForTransIdOnNode(transId) # seems like account creation needs to be finlized before transfer can happen
            trans = self.transferFunds(creatorAccount, account, Node.currencyIntToStr(stakedDeposit, CORE_SYMBOL), "init")
            transId=Node.getTransId(trans)

        if waitForTransBlock and not self.waitForTransIdOnNode(transId):
            return None

        return trans

    # Create account and return creation transactions. Return transaction json object
    # waitForTransBlock: wait on creation transaction id to appear in a block
    def createAccount(self, account, creatorAccount, stakedDeposit=1000, waitForTransBlock=False):
        cmd="%s %s create account -j %s %s %s %s" % (
            Utils.ClientPath, self.endpointArgs, creatorAccount.name, account.name,
            account.ownerPublicKey, account.activePublicKey)

        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        trans=None
        try:
            trans=Node.runCmdReturnJson(cmd)
            transId=Node.getTransId(trans)
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            Utils.Print("ERROR: Exception during account creation. %s" % (msg))
            return None

        if stakedDeposit > 0:
            self.waitForTransIdOnNode(transId) # seems like account creation needs to be finlized before transfer can happen
            trans = self.transferFunds(creatorAccount, account, "%0.04f %s" % (stakedDeposit/10000, CORE_SYMBOL), "init")
            transId=Node.getTransId(trans)

        if waitForTransBlock and not self.waitForTransIdOnNode(transId):
            return None

        return trans

    def getAccount(self, name):
        assert(isinstance(name, str))
        cmd="%s %s get account -j %s" % (Utils.ClientPath, self.endpointArgs, name)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        try:
            trans=Node.runCmdReturnJson(cmd)
            return trans
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            Utils.Print("ERROR: Exception during get account. %s" % (msg))
            return None

    def getAccountFromDb(self, name):
        cmd="%s %s" % (Utils.MongoPath, self.mongoEndpointArgs)
        subcommand='db.Accounts.findOne({"name" : "%s"})' % (name)
        if Utils.Debug: Utils.Print("cmd: echo '%s' | %s" % (subcommand, cmd))
        try:
            trans=Node.runMongoCmdReturnJson(cmd.split(), subcommand)
            return trans
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            Utils.Print("ERROR: Exception during get account from db. %s" % (msg))
            return None

    def getTable(self, contract, scope, table):
        cmd="%s %s get table %s %s %s" % (Utils.ClientPath, self.endpointArgs, contract, scope, table)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        try:
            trans=Node.runCmdReturnJson(cmd)
            return trans
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            Utils.Print("ERROR: Exception during table retrieval. %s" % (msg))
            return None

    def getTableAccountBalance(self, contract, scope):
        assert(isinstance(contract, str))
        assert(isinstance(scope, str))
        table="accounts"
        trans = self.getTable(contract, scope, table)
        assert(trans)
        try:
            return trans["rows"][0]["balance"]
        except (TypeError, KeyError) as _:
            print("Transaction parsing failed. Transaction: %s" % (trans))
            raise

    def getCurrencyBalance(self, contract, account, symbol=CORE_SYMBOL):
        """returns raw output from get currency balance e.g. '99999.9950 CUR'"""
        assert(contract)
        assert(isinstance(contract, str))
        assert(account)
        assert(isinstance(account, str))
        assert(symbol)
        assert(isinstance(symbol, str))
        cmd="%s %s get currency balance %s %s %s" % (Utils.ClientPath, self.endpointArgs, contract, account, symbol)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        try:
            trans=Node.runCmdReturnStr(cmd)
            return trans
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            Utils.Print("ERROR: Exception during get currency stats. %s" % (msg))
            return None

    def getCurrencyStats(self, contract, symbol=CORE_SYMBOL):
        """returns Json output from get currency stats."""
        assert(contract)
        assert(isinstance(contract, str))
        assert(symbol)
        assert(isinstance(symbol, str))
        cmd="%s %s get currency stats %s %s" % (Utils.ClientPath, self.endpointArgs, contract, symbol)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        try:
            trans=Node.runCmdReturnJson(cmd)
            return trans
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            Utils.Print("ERROR: Exception during get currency stats. %s" % (msg))
            return None

    # Verifies account. Returns "get account" json return object
    def verifyAccount(self, account):
        if not self.enableMongo:
            ret=self.getAccount(account.name)
            if ret is not None:
                account_name=ret["account_name"]
                if account_name is None:
                    Utils.Print("ERROR: Failed to verify account creation.", account.name)
                    return None
                return ret
        else:
            for _ in range(2):
                ret=self.getAccountFromDb(account.name)
                if ret is not None:
                    account_name=ret["name"]
                    if account_name is None:
                        Utils.Print("ERROR: Failed to verify account creation.", account.name)
                        return None
                    return ret
                if self.mongoSyncTime is not None:
                    if Utils.Debug: Utils.Print("cmd: sleep %d seconds" % (self.mongoSyncTime))
                    time.sleep(self.mongoSyncTime)

        return None

    def waitForBlockNumOnNode(self, blockNum, timeout=None):
        lam = lambda: self.doesNodeHaveBlockNum(blockNum)
        ret=Utils.waitForBool(lam, timeout)
        return ret

    def waitForTransIdOnNode(self, transId, timeout=None):
        lam = lambda: self.doesNodeHaveTransId(transId)
        ret=Utils.waitForBool(lam, timeout)
        return ret

    def waitForNextBlock(self, timeout=None):
        num=self.getHeadBlockNum()
        lam = lambda: self.getHeadBlockNum() > num
        ret=Utils.waitForBool(lam, timeout)
        return ret

    # Trasfer funds. Returns "transfer" json return object
    def transferFunds(self, source, destination, amountStr, memo="memo", force=False, waitForTransBlock=False):
        assert isinstance(amountStr, str)
        assert(source)
        assert(isinstance(source, Account))
        assert(destination)
        assert(isinstance(destination, Account))

        cmd="%s %s -v transfer -j %s %s" % (
            Utils.ClientPath, self.endpointArgs, source.name, destination.name)
        cmdArr=cmd.split()
        cmdArr.append(amountStr)
        cmdArr.append(memo)
        if force:
            cmdArr.append("-f")
        s=" ".join(cmdArr)
        if Utils.Debug: Utils.Print("cmd: %s" % (s))
        trans=None
        try:
            trans=Node.__runCmdArrReturnJson(cmdArr)
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            Utils.Print("ERROR: Exception during funds transfer. %s" % (msg))
            return None

        assert(trans)
        transId=Node.getTransId(trans)
        if waitForTransBlock and not self.waitForTransIdOnNode(transId):
            return None

        return trans

    @staticmethod
    def currencyStrToInt(balanceStr):
        """Converts currency string of form "12.3456 SYS" to int 123456"""
        assert(isinstance(balanceStr, str))
        balanceStr=balanceStr.split()[0]
        #balance=int(decimal.Decimal(balanceStr[1:])*10000)
        balance=int(decimal.Decimal(balanceStr)*10000)

        return balance

    @staticmethod
    def currencyIntToStr(balance, symbol):
        """Converts currency int of form 123456 to string "12.3456 SYS" where SYS is symbol string"""
        assert(isinstance(balance, int))
        assert(isinstance(symbol, str))
        balanceStr="%.04f %s" % (balance/10000.0, symbol)

        return balanceStr

    def validateFunds(self, initialBalances, transferAmount, source, accounts):
        """Validate each account has the expected SYS balance. Validate cumulative balance matches expectedTotal."""
        assert(source)
        assert(isinstance(source, Account))
        assert(accounts)
        assert(isinstance(accounts, list))
        assert(len(accounts) > 0)
        assert(initialBalances)
        assert(isinstance(initialBalances, dict))
        assert(isinstance(transferAmount, int))

        currentBalances=self.getBalances([source] + accounts)
        assert(currentBalances)
        assert(isinstance(currentBalances, dict))
        assert(len(initialBalances) == len(currentBalances))

        if len(currentBalances) != len(initialBalances):
            Utils.Print("ERROR: validateFunds> accounts length mismatch. Initial: %d, current: %d" % (len(initialBalances), len(currentBalances)))
            return False

        for key, value in currentBalances.items():
            initialBalance = initialBalances[key]
            assert(initialBalances)
            expectedInitialBalance = value - transferAmount
            if key is source:
                expectedInitialBalance = value + (transferAmount*len(accounts))

            if (initialBalance != expectedInitialBalance):
                Utils.Print("ERROR: validateFunds> Expected: %d, actual: %d for account %s" %
                            (expectedInitialBalance, initialBalance, key.name))
                return False

    def getBalances(self, accounts):
        """Returns a dictionary with account balances keyed by accounts"""
        assert(accounts)
        assert(isinstance(accounts, list))

        balances={}
        for account in accounts:
            balance = self.getAccountBalance(account.name)
            balances[account]=balance

        return balances

    # Gets accounts mapped to key. Returns json object
    def getAccountsByKey(self, key):
        cmd="%s %s get accounts %s" % (Utils.ClientPath, self.endpointArgs, key)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        try:
            trans=Node.runCmdReturnJson(cmd)
            return trans
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            Utils.Print("ERROR: Exception during accounts by key retrieval. %s" % (msg))
            return None

    # Get actions mapped to an account (cl get actions)
    def getActions(self, account, pos=-1, offset=-1):
        assert(isinstance(account, Account))
        assert(isinstance(pos, int))
        assert(isinstance(offset, int))

        cmd="%s %s get actions -j %s %d %d" % (Utils.ClientPath, self.endpointArgs, account.name, pos, offset)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        try:
            actions=Node.runCmdReturnJson(cmd)
            return actions
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            Utils.Print("ERROR: Exception during actions by account retrieval. %s" % (msg))
            return None

    # Gets accounts mapped to key. Returns array
    def getAccountsArrByKey(self, key):
        trans=self.getAccountsByKey(key)
        assert(trans)
        assert("account_names" in trans)
        accounts=trans["account_names"]
        return accounts

    def getServants(self, name):
        cmd="%s %s get servants %s" % (Utils.ClientPath, self.endpointArgs, name)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        try:
            trans=Node.runCmdReturnJson(cmd)
            return trans
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            Utils.Print("ERROR: Exception during servants retrieval. %s" % (msg))
            return None

    def getServantsArr(self, name):
        trans=self.getServants(name)
        servants=trans["controlled_accounts"]
        return servants

    def getAccountBalanceStr(self, scope):
        """Returns SYS currency0000 account balance from cl get table command. Returned balance is string following syntax "98.0311 SYS". """
        assert isinstance(scope, str)
        if not self.enableMongo:
            amount=self.getTableAccountBalance("io.token", scope)
            if Utils.Debug: Utils.Print("getNodeAccountBalance %s %s" % (scope, amount))
            assert isinstance(amount, str)
            return amount
        else:
            if self.mongoSyncTime is not None:
                if Utils.Debug: Utils.Print("cmd: sleep %d seconds" % (self.mongoSyncTime))
                time.sleep(self.mongoSyncTime)

            account=self.getAccountFromDb(scope)
            if account is not None:
                balance=account["_balance"]
                return balance

        return None

    def getAccountBalance(self, scope):
        """Returns SYS currency0000 account balance from cl get table command. Returned balance is an integer e.g. 980311. """
        balanceStr=self.getAccountBalanceStr(scope)
        balance=Node.currencyStrToInt(balanceStr)
        return balance

    def getAccountCodeHash(self, account):
        cmd="%s %s get code %s" % (Utils.ClientPath, self.endpointArgs, account)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        try:
            retStr=Utils.checkOutput(cmd.split())
            #Utils.Print ("get code> %s"% retStr)
            p=re.compile(r'code\shash: (\w+)\n', re.MULTILINE)
            m=p.search(retStr)
            if m is None:
                msg="Failed to parse code hash."
                Utils.Print("ERROR: "+ msg)
                return None

            return m.group(1)
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            Utils.Print("ERROR: Exception during code hash retrieval. %s" % (msg))
            return None

    # publish contract and return transaction as json object
    def publishContract(self, account, contractDir, wastFile, abiFile, waitForTransBlock=False, shouldFail=False):
        cmd="%s %s -v set contract -j %s %s" % (Utils.ClientPath, self.endpointArgs, account, contractDir)
        cmd += "" if wastFile is None else (" "+ wastFile)
        cmd += "" if abiFile is None else (" " + abiFile)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        trans=None
        try:
            trans=Node.runCmdReturnJson(cmd, trace=False)
        except subprocess.CalledProcessError as ex:
            if not shouldFail:
                msg=ex.output.decode("utf-8")
                Utils.Print("ERROR: Exception during code hash retrieval. %s" % (msg))
                return None
            else:
                retMap={}
                retMap["returncode"]=ex.returncode
                retMap["cmd"]=ex.cmd
                retMap["output"]=ex.output
                # commented below as they are available only in Python3.5 and above
                # retMap["stdout"]=ex.stdout
                # retMap["stderr"]=ex.stderr
                return retMap

        if shouldFail:
            Utils.Print("ERROR: The publish contract did not fail as expected.")
            return None

        Node.validateTransaction(trans)
        transId=Node.getTransId(trans)
        if waitForTransBlock and not self.waitForTransIdOnNode(transId):
            return None
        return trans

    def getTableRows(self, contract, scope, table):
        jsonData=self.getTable(contract, scope, table)
        if jsonData is None:
            return None
        rows=jsonData["rows"]
        return rows

    def getTableRow(self, contract, scope, table, idx):
        if idx < 0:
            Utils.Print("ERROR: Table index cannot be negative. idx: %d" % (idx))
            return None
        rows=self.getTableRows(contract, scope, table)
        if rows is None or idx >= len(rows):
            Utils.Print("ERROR: Retrieved table does not contain row %d" % idx)
            return None
        row=rows[idx]
        return row

    def getTableColumns(self, contract, scope, table):
        row=self.getTableRow(contract, scope, table, 0)
        keys=list(row.keys())
        return keys

    # returns tuple with transaction and
    def pushMessage(self, account, action, data, opts, silentErrors=False):
        cmd="%s %s push action -j %s %s" % (Utils.ClientPath, self.endpointArgs, account, action)
        cmdArr=cmd.split()
        if data is not None:
            cmdArr.append(data)
        if opts is not None:
            cmdArr += opts.split()
        s=" ".join(cmdArr)
        if Utils.Debug: Utils.Print("cmd: %s" % (s))
        try:
            trans=Node.__runCmdArrReturnJson(cmdArr)
            return (True, trans)
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            if not silentErrors:
                Utils.Print("ERROR: Exception during push message. %s" % (msg))
            return (False, msg)

    def setPermission(self, account, code, pType, requirement, waitForTransBlock=False):
        cmd="%s %s set action permission -j %s %s %s %s" % (
            Utils.ClientPath, self.endpointArgs, account, code, pType, requirement)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        trans=None
        try:
            trans=Node.runCmdReturnJson(cmd)
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            Utils.Print("ERROR: Exception during set permission. %s" % (msg))
            return None

        transId=Node.getTransId(trans)
        if waitForTransBlock and not self.waitForTransIdOnNode(transId):
            return None
        return trans

    def getInfo(self, silentErrors=False):
        cmd="%s %s get info" % (Utils.ClientPath, self.endpointArgs)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        try:
            trans=Node.runCmdReturnJson(cmd)
            return trans
        except subprocess.CalledProcessError as ex:
            if not silentErrors:
                msg=ex.output.decode("utf-8")
                Utils.Print("ERROR: Exception during get info. %s" % (msg))
            return None

    def getBlockFromDb(self, idx):
        cmd="%s %s" % (Utils.MongoPath, self.mongoEndpointArgs)
        subcommand="db.Blocks.find().sort({\"_id\":%d}).limit(1).pretty()" % (idx)
        if Utils.Debug: Utils.Print("cmd: echo \"%s\" | %s" % (subcommand, cmd))
        try:
            trans=Node.runMongoCmdReturnJson(cmd.split(), subcommand)
            return trans
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            Utils.Print("ERROR: Exception during get db block. %s" % (msg))
            return None

    def checkPulse(self):
        info=self.getInfo(True)
        return False if info is None else True

    def getHeadBlockNum(self):
        """returns head block number(string) as returned by cl get info."""
        if not self.enableMongo:
            info=self.getInfo()
            if info is not None:
                headBlockNumTag="head_block_num"
                return info[headBlockNumTag]
        else:
            # Either this implementation or the one in getIrreversibleBlockNum are likely wrong.
            block=self.getBlockFromDb(-1)
            if block is not None:
                blockNum=block["block_num"]
                return blockNum
        return None

    def getIrreversibleBlockNum(self):
        if not self.enableMongo:
            info=self.getInfo()
            if info is not None:
                return info["last_irreversible_block_num"]
        else:
            # Either this implementation or the one in getHeadBlockNum are likely wrong.
            block=self.getBlockFromDb(-1)
            if block is not None:
                blockNum=block["block_num"]
                return blockNum
        return None

    def kill(self, killSignal):
        if Utils.Debug: Utils.Print("Killing node: %s" % (self.cmd))
        assert(self.pid is not None)
        try:
            os.kill(self.pid, killSignal)
        except OSError as ex:
            Utils.Print("ERROR: Failed to kill node (%d)." % (self.cmd), ex)
            return False

        # wait for kill validation
        def myFunc():
            try:
                os.kill(self.pid, 0) #check if process with pid is running
            except OSError as _:
                return True
            return False

        if not Utils.waitForBool(myFunc):
            Utils.Print("ERROR: Failed to kill node (%s)." % (self.cmd), ex)
            return False

        # mark node as killed
        self.pid=None
        self.killed=True
        return True

    # TBD: make nodeId an internal property
    def relaunch(self, nodeId, chainArg):

        running=True
        try:
            os.kill(self.pid, 0) #check if process with pid is running
        except OSError as _:
            running=False

        if running:
            Utils.Print("WARNING: A process with pid (%d) is already running." % (self.pid))
        else:
            if Utils.Debug: Utils.Print("Launching node process, Id: %d" % (nodeId))
            dataDir="var/lib/node_%02d" % (nodeId)
            dt = datetime.datetime.now()
            dateStr="%d_%02d_%02d_%02d_%02d_%02d" % (
                dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
            stdoutFile="%s/stdout.%s.txt" % (dataDir, dateStr)
            stderrFile="%s/stderr.%s.txt" % (dataDir, dateStr)
            with open(stdoutFile, 'w') as sout, open(stderrFile, 'w') as serr:
                cmd=self.cmd + ("" if chainArg is None else (" " + chainArg))
                Utils.Print("cmd: %s" % (cmd))
                popen=subprocess.Popen(cmd.split(), stdout=sout, stderr=serr)
                self.pid=popen.pid

        self.killed=False
        return True


###########################################################################################

Wallet=namedtuple("Wallet", "name password host port")
# pylint: disable=too-many-instance-attributes
class WalletMgr(object):
    __walletLogFile="test_kd_output.log"
    __walletDataDir="test_wallet_0"

    # pylint: disable=too-many-arguments
    # walletd [True|False] True=Launch wallet(kd) process; False=Manage launch process externally.
    def __init__(self, walletd, nodPort=8888, nodHost="localhost", port=8899, host="localhost"):
        self.walletd=walletd
        self.nodPort=nodPort
        self.nodHost=nodHost
        self.port=port
        self.host=host
        self.wallets={}
        self.__walletPid=None
        self.endpointArgs="--url http://%s:%d" % (self.nodHost, self.nodPort)
        self.walletEndpointArgs=""
        if self.walletd:
            self.walletEndpointArgs += " --wallet-url http://%s:%d" % (self.host, self.port)
            self.endpointArgs += self.walletEndpointArgs

    def launch(self):
        if not self.walletd:
            Utils.Print("ERROR: Wallet Manager wasn't configured to launch kd")
            return False

        cmd="%s --data-dir %s --config-dir %s --http-server-address=%s:%d" % (
            Utils.WalletPath, WalletMgr.__walletDataDir, WalletMgr.__walletDataDir, self.host, self.port)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        with open(WalletMgr.__walletLogFile, 'w') as sout, open(WalletMgr.__walletLogFile, 'w') as serr:
            popen=subprocess.Popen(cmd.split(), stdout=sout, stderr=serr)
            self.__walletPid=popen.pid

        # Give kd time to warm up
        time.sleep(1)
        return True

    def create(self, name):
        wallet=self.wallets.get(name)
        if wallet is not None:
            if Utils.Debug: Utils.Print("Wallet \"%s\" already exists. Returning same." % name)
            return wallet
        p = re.compile(r'\n\"(\w+)\"\n', re.MULTILINE)
        cmd="%s %s wallet create --name %s" % (Utils.ClientPath, self.endpointArgs, name)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        retStr=subprocess.check_output(cmd.split()).decode("utf-8")
        #Utils.Print("create: %s" % (retStr))
        m=p.search(retStr)
        if m is None:
            Utils.Print("ERROR: wallet password parser failure")
            return None
        p=m.group(1)
        wallet=Wallet(name, p, self.host, self.port)
        self.wallets[name] = wallet

        return wallet

    def importKey(self, account, wallet):
        warningMsg="Key already in wallet"
        cmd="%s %s wallet import --name %s %s" % (
            Utils.ClientPath, self.endpointArgs, wallet.name, account.ownerPrivateKey)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        try:
            subprocess.check_output(cmd.split(), stderr=subprocess.STDOUT).decode("utf-8")
        except subprocess.CalledProcessError as ex:
            msg=ex.output.decode("utf-8")
            if warningMsg in msg:
                Utils.Print("WARNING: This key is already imported into the wallet.")
            else:
                Utils.Print("ERROR: Failed to import account owner key %s. %s" % (account.ownerPrivateKey, msg))
                return False

        if account.activePrivateKey is None:
            Utils.Print("WARNING: Active private key is not defined for account \"%s\"" % (account.name))
        else:
            cmd="%s %s wallet import --name %s %s" % (
                Utils.ClientPath, self.endpointArgs, wallet.name, account.activePrivateKey)
            if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
            try:
                subprocess.check_output(cmd.split(), stderr=subprocess.STDOUT).decode("utf-8")
            except subprocess.CalledProcessError as ex:
                msg=ex.output.decode("utf-8")
                if warningMsg in msg:
                    Utils.Print("WARNING: This key is already imported into the wallet.")
                else:
                    Utils.Print("ERROR: Failed to import account active key %s. %s" %
                                (account.activePrivateKey, msg))
                    return False

        return True

    def lockWallet(self, wallet):
        cmd="%s %s wallet lock --name %s" % (Utils.ClientPath, self.endpointArgs, wallet.name)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        if 0 != subprocess.call(cmd.split(), stdout=Utils.FNull):
            Utils.Print("ERROR: Failed to lock wallet %s." % (wallet.name))
            return False

        return True

    def unlockWallet(self, wallet):
        cmd="%s %s wallet unlock --name %s" % (Utils.ClientPath, self.endpointArgs, wallet.name)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        popen=subprocess.Popen(cmd.split(), stdout=Utils.FNull, stdin=subprocess.PIPE)
        _, errs = popen.communicate(input=wallet.password.encode("utf-8"))
        if 0 != popen.wait():
            Utils.Print("ERROR: Failed to unlock wallet %s: %s" % (wallet.name, errs.decode("utf-8")))
            return False

        return True

    def lockAllWallets(self):
        cmd="%s %s wallet lock_all" % (Utils.ClientPath, self.endpointArgs)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        if 0 != subprocess.call(cmd.split(), stdout=Utils.FNull):
            Utils.Print("ERROR: Failed to lock all wallets.")
            return False

        return True

    def getOpenWallets(self):
        wallets=[]

        p = re.compile(r'\s+\"(\w+)\s\*\",?\n', re.MULTILINE)
        cmd="%s %s wallet list" % (Utils.ClientPath, self.endpointArgs)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        retStr=subprocess.check_output(cmd.split()).decode("utf-8")
        #Utils.Print("retStr: %s" % (retStr))
        m=p.findall(retStr)
        if m is None:
            Utils.Print("ERROR: wallet list parser failure")
            return None
        wallets=m

        return wallets

    def getKeys(self):
        keys=[]

        p = re.compile(r'\n\s+\"(\w+)\"\n', re.MULTILINE)
        cmd="%s %s wallet keys" % (Utils.ClientPath, self.endpointArgs)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        retStr=subprocess.check_output(cmd.split()).decode("utf-8")
        #Utils.Print("retStr: %s" % (retStr))
        m=p.findall(retStr)
        if m is None:
            Utils.Print("ERROR: wallet keys parser failure")
            return None
        keys=m

        return keys


    def dumpErrorDetails(self):
        Utils.Print("=================================================================")
        if self.__walletPid is not None:
            Utils.Print("Contents of %s:" % (WalletMgr.__walletLogFile))
            Utils.Print("=================================================================")
            with open(WalletMgr.__walletLogFile, "r") as f:
                shutil.copyfileobj(f, sys.stdout)

    @staticmethod
    def killall():
        cmd="pkill -9 %s" % (Utils.WalletName)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        subprocess.call(cmd.split())

    @staticmethod
    def cleanup():
        dataDir=WalletMgr.__walletDataDir
        if os.path.isdir(dataDir) and os.path.exists(dataDir):
            shutil.rmtree(WalletMgr.__walletDataDir)



###########################################################################################
class Cluster(object):
    __chainSyncStrategies=Utils.getChainStrategies()
    __chainSyncStrategy=None
    __WalletName="MyWallet"
    __localHost="localhost"
    __BiosHost="localhost"
    __BiosPort=8788

    # pylint: disable=too-many-arguments
    # walletd [True|False] Is kd running. If not load the wallet plugin
    def __init__(self, walletd=False, localCluster=True, host="localhost", port=8888, walletHost="localhost", walletPort=8899, enableMongo=False, mongoHost="localhost", mongoPort=27017, mongoDb="test", defproduceraPrvtKey=None, defproducerbPrvtKey=None, staging=False):
        """Cluster container.
        walletd [True|False] Is wallet kd running. If not load the wallet plugin
        localCluster [True|False] Is cluster local to host.
        host:  server host
        port:  server port
        walletHost:  wallet host
        walletPort: wos wallet port
        enableMongo: Include mongoDb support, configures  mongo plugin
        mongoHost: MongoDB host
        mongoPort: MongoDB port
        defproduceraPrvtKey: Defproducera account private key
        defproducerbPrvtKey: Defproducerb account private key
        """
        self.accounts={}
        self.nodes={}
        self.localCluster=localCluster
        self.wallet=None
        self.walletd=walletd
        self.enableMongo=enableMongo
        self.mongoHost=mongoHost
        self.mongoPort=mongoPort
        self.mongoDb=mongoDb
        self.walletMgr=None
        self.host=host
        self.port=port
        self.walletHost=walletHost
        self.walletPort=walletPort
        self.walletEndpointArgs=""
        if self.walletd:
            self.walletEndpointArgs += " --wallet-url http://%s:%d" % (self.walletHost, self.walletPort)
        self.mongoEndpointArgs=""
        self.mongoUri=""
        if self.enableMongo:
            self.mongoUri="mongodb://%s:%d/%s" % (mongoHost, mongoPort, mongoDb)
            self.mongoEndpointArgs += "--host %s --port %d %s" % (mongoHost, mongoPort, mongoDb)
        self.staging=staging
        # init accounts
        self.defproduceraAccount=Account("defproducera")
        self.defproducerbAccount=Account("defproducerb")
        self.ioAccount=Account("io")
        self.defproduceraAccount.ownerPrivateKey=defproduceraPrvtKey
        self.defproduceraAccount.activePrivateKey=defproduceraPrvtKey
        self.defproducerbAccount.ownerPrivateKey=defproducerbPrvtKey
        self.defproducerbAccount.activePrivateKey=defproducerbPrvtKey


    def setChainStrategy(self, chainSyncStrategy=Utils.SyncReplayTag):
        self.__chainSyncStrategy=self.__chainSyncStrategies.get(chainSyncStrategy)
        if self.__chainSyncStrategy is None:
            self.__chainSyncStrategy=self.__chainSyncStrategies.get("none")

    def setWalletMgr(self, walletMgr):
        self.walletMgr=walletMgr

    # launch local nodes and set self.nodes
    # pylint: disable=too-many-locals
    # pylint: disable=too-many-return-statements
    # pylint: disable=too-many-branches
    # pylint: disable=too-many-statements
    def launch(self, pnodes=1, totalNodes=1, prodCount=1, topo="mesh", delay=1, onlyBios=False, dontKill=False):
        """Launch cluster.
        pnodes: producer nodes count
        totalNodes: producer + non-producer nodes count
        prodCount: producers per prodcuer node count
        topo: cluster topology (as defined by launcher)
        delay: delay between individual nodes launch (as defined by launcher)
          delay 0 exposes a bootstrap bug where producer handover may have a large gap confusing nodes and bringing system to a halt.
        """
        if not self.localCluster:
            Utils.Print("WARNING: Cluster not local, not launching %s." % (Utils.ServerName))
            return True

        if len(self.nodes) > 0:
            raise RuntimeError("Cluster already running.")

        cmd="%s -p %s -n %s -s %s -d %s -i %s -f --p2p-plugin bnet" % (
            Utils.LauncherPath, pnodes, totalNodes, topo, delay, datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3])
        cmdArr=cmd.split()
        if self.staging:
            cmdArr.append("--nogen")

        nodArgs="--max-transaction-time 5000 --filter-on *"
        if not self.walletd:
            nodArgs += " --plugin io::wallet_api_plugin"
        if self.enableMongo:
            nodArgs += " --plugin io::mongo_db_plugin --delete-all-blocks --mongodb-uri %s" % self.mongoUri

        if nodArgs:
            cmdArr.append("--nod")
            cmdArr.append(nodArgs)

        s=" ".join(cmdArr)
        if Utils.Debug: Utils.Print("cmd: %s" % (s))
        if 0 != subprocess.call(cmdArr):
            Utils.Print("ERROR: Launcher failed to launch.")
            return False

        self.nodes=list(range(totalNodes)) # placeholder for cleanup purposes only

        nodes=self.discoverLocalNodes(totalNodes, timeout=Utils.systemWaitTimeout)
        if nodes is None or totalNodes != len(nodes):
            Utils.Print("ERROR: Unable to validate %s instances, expected: %d, actual: %d" %
                          (Utils.ServerName, totalNodes, len(nodes)))
            return False

        self.nodes=nodes

        if onlyBios:
            biosNode=Node(Cluster.__BiosHost, Cluster.__BiosPort)
            biosNode.setWalletEndpointArgs(self.walletEndpointArgs)
            if not biosNode.checkPulse():
                Utils.Print("ERROR: Bios node doesn't appear to be running...")
                return False

            self.nodes=[biosNode]

        # ensure cluster node are inter-connected by ensuring everyone has block 1
        Utils.Print("Cluster viability smoke test. Validate every cluster node has block 1. ")
        if not self.waitOnClusterBlockNumSync(1):
            Utils.Print("ERROR: Cluster doesn't seem to be in sync. Some nodes missing block 1")
            return False

        Utils.Print("Bootstrap cluster.")
        if not Cluster.bootstrap(totalNodes, prodCount, Cluster.__BiosHost, Cluster.__BiosPort, dontKill, onlyBios):
            Utils.Print("ERROR: Bootstrap failed.")
            return False

        # validate iniX accounts can be retrieved

        producerKeys=Cluster.parseClusterKeys(totalNodes)
        if producerKeys is None:
            Utils.Print("ERROR: Unable to parse cluster info")
            return False

        init1Keys=producerKeys["defproducera"]
        init2Keys=producerKeys["defproducerb"]
        if init1Keys is None or init2Keys is None:
            Utils.Print("ERROR: Failed to parse defproducera or intb private keys from cluster config files.")
        self.defproduceraAccount.ownerPrivateKey=init1Keys["private"]
        self.defproduceraAccount.ownerPublicKey=init1Keys["public"]
        self.defproduceraAccount.activePrivateKey=init1Keys["private"]
        self.defproduceraAccount.activePublicKey=init1Keys["public"]
        self.defproducerbAccount.ownerPrivateKey=init2Keys["private"]
        self.defproducerbAccount.ownerPublicKey=init2Keys["public"]
        self.defproducerbAccount.activePrivateKey=init2Keys["private"]
        self.defproducerbAccount.activePublicKey=init2Keys["public"]
        producerKeys.pop("io")

        return True

    # Initialize the default nodes (at present just the root node)
    def initializeNodes(self, defproduceraPrvtKey=None, defproducerbPrvtKey=None, onlyBios=False):
        port=Cluster.__BiosPort if onlyBios else self.port
        host=Cluster.__BiosHost if onlyBios else self.host
        node=Node(host, port, enableMongo=self.enableMongo, mongoHost=self.mongoHost, mongoPort=self.mongoPort, mongoDb=self.mongoDb)
        node.setWalletEndpointArgs(self.walletEndpointArgs)
        if Utils.Debug: Utils.Print("Node:", node)

        node.checkPulse()
        self.nodes=[node]

        if defproduceraPrvtKey is not None:
            self.defproduceraAccount.ownerPrivateKey=defproduceraPrvtKey
            self.defproduceraAccount.activePrivateKey=defproduceraPrvtKey

        if defproducerbPrvtKey is not None:
            self.defproducerbAccount.ownerPrivateKey=defproducerbPrvtKey
            self.defproducerbAccount.activePrivateKey=defproducerbPrvtKey

        return True

    # Initialize nodes from the Json nodes string
    def initializeNodesFromJson(self, nodesJsonStr):
        nodesObj= json.loads(nodesJsonStr)
        if nodesObj is None:
            Utils.Print("ERROR: Invalid Json string.")
            return False

        if "keys" in nodesObj:
            keysMap=nodesObj["keys"]

            if "defproduceraPrivateKey" in keysMap:
                defproduceraPrivateKey=keysMap["defproduceraPrivateKey"]
                self.defproduceraAccount.ownerPrivateKey=defproduceraPrivateKey

            if "defproducerbPrivateKey" in keysMap:
                defproducerbPrivateKey=keysMap["defproducerbPrivateKey"]
                self.defproducerbAccount.ownerPrivateKey=defproducerbPrivateKey

        nArr=nodesObj["nodes"]
        nodes=[]
        for n in nArr:
            port=n["port"]
            host=n["host"]
            node=Node(host, port)
            node.setWalletEndpointArgs(self.walletEndpointArgs)
            if Utils.Debug: Utils.Print("Node:", node)

            node.checkPulse()
            nodes.append(node)

        self.nodes=nodes
        return True

    # manually set nodes, alternative to explicit launch
    def setNodes(self, nodes):
        self.nodes=nodes

    # If a last transaction exists wait for it on root node, then collect its head block number.
    #  Wait on this block number on each cluster node
    def waitOnClusterSync(self, timeout=None):
        targetHeadBlockNum=self.nodes[0].getHeadBlockNum() #get root nodes head block num
        if Utils.Debug: Utils.Print("Head block number on root node: %d" % (targetHeadBlockNum))
        if targetHeadBlockNum == -1:
            return False

        return self.waitOnClusterBlockNumSync(targetHeadBlockNum, timeout)

    def waitOnClusterBlockNumSync(self, targetHeadBlockNum, timeout=None):

        def doNodesHaveBlockNum(nodes, targetHeadBlockNum):
            for node in nodes:
                if (not node.killed) and (not node.doesNodeHaveBlockNum(targetHeadBlockNum)):
                    return False

            return True

        lam = lambda: doNodesHaveBlockNum(self.nodes, targetHeadBlockNum)
        ret=Utils.waitForBool(lam, timeout)
        return ret

    @staticmethod
    def createAccountKeys(count):
        accounts=[]
        p = re.compile('Private key: (.+)\nPublic key: (.+)\n', re.MULTILINE)
        for _ in range(0, count):
            try:
                cmd="%s create key" % (Utils.ClientPath)
                if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
                keyStr=subprocess.check_output(cmd.split(), stderr=subprocess.STDOUT).decode("utf-8")
                m=p.search(keyStr)
                if m is None:
                    Utils.Print("ERROR: Owner key creation regex mismatch")
                    break

                ownerPrivate=m.group(1)
                ownerPublic=m.group(2)

                cmd="%s create key" % (Utils.ClientPath)
                if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
                keyStr=subprocess.check_output(cmd.split(), stderr=subprocess.STDOUT).decode("utf-8")
                m=p.match(keyStr)
                if m is None:
                    Utils.Print("ERROR: Active key creation regex mismatch")
                    break

                activePrivate=m.group(1)
                activePublic=m.group(2)

                name=''.join(random.choice(string.ascii_lowercase) for _ in range(12))
                account=Account(name)
                account.ownerPrivateKey=ownerPrivate
                account.ownerPublicKey=ownerPublic
                account.activePrivateKey=activePrivate
                account.activePublicKey=activePublic
                accounts.append(account)
                if Utils.Debug: Utils.Print("name: %s, key(owner): ['%s', '%s], key(active): ['%s', '%s']" % (name, ownerPublic, ownerPrivate, activePublic, activePrivate))

            except subprocess.CalledProcessError as ex:
                msg=ex.output.decode("utf-8")
                Utils.Print("ERROR: Exception during key creation. %s" % (msg))
                break

        if count != len(accounts):
            Utils.Print("Account keys creation failed. Expected %d, actual: %d" % (count, len(accounts)))
            return None

        return accounts

    # create account keys and import into wallet. Wallet initialization will be user responsibility
    # also imports defproducera and defproducerb accounts
    def populateWallet(self, accountsCount, wallet):
        if self.walletMgr is None:
            Utils.Print("ERROR: WalletMgr hasn't been initialized.")
            return False

        accounts=None
        if accountsCount > 0:
            Utils.Print ("Create account keys.")
            accounts = self.createAccountKeys(accountsCount)
            if accounts is None:
                Utils.Print("Account keys creation failed.")
                return False

        Utils.Print("Importing keys for account %s into wallet %s." % (self.defproduceraAccount.name, wallet.name))
        if not self.walletMgr.importKey(self.defproduceraAccount, wallet):
            Utils.Print("ERROR: Failed to import key for account %s" % (self.defproduceraAccount.name))
            return False

        Utils.Print("Importing keys for account %s into wallet %s." % (self.defproducerbAccount.name, wallet.name))
        if not self.walletMgr.importKey(self.defproducerbAccount, wallet):
            Utils.Print("ERROR: Failed to import key for account %s" % (self.defproducerbAccount.name))
            return False

        for account in accounts:
            Utils.Print("Importing keys for account %s into wallet %s." % (account.name, wallet.name))
            if not self.walletMgr.importKey(account, wallet):
                Utils.Print("ERROR: Failed to import key for account %s" % (account.name))
                return False

        self.accounts=accounts
        return True

    def getNode(self, nodeId=0):
        return self.nodes[nodeId]

    def getNodes(self):
        return self.nodes

    # Spread funds across accounts with transactions spread through cluster nodes.
    #  Validate transactions are synchronized on root node
    def spreadFunds(self, source, accounts, amount=1):
        assert(source)
        assert(isinstance(source, Account))
        assert(accounts)
        assert(isinstance(accounts, list))
        assert(len(accounts) > 0)
        Utils.Print("len(accounts): %d" % (len(accounts)))

        count=len(accounts)
        transferAmount=(count*amount)+amount
        transferAmountStr=Node.currencyIntToStr(transferAmount, CORE_SYMBOL)
        node=self.nodes[0]
        fromm=source
        to=accounts[0]
        Utils.Print("Transfer %s units from account %s to %s on  server port %d" % (
            transferAmountStr, fromm.name, to.name, node.port))
        trans=node.transferFunds(fromm, to, transferAmountStr)
        assert(trans)
        transId=Node.getTransId(trans)
        if transId is None:
            return False

        if Utils.Debug: Utils.Print("Funds transfered on transaction id %s." % (transId))

        nextIdx=-1
        for i in range(0, count):
            account=accounts[i]
            nextInstanceFound=False
            for _ in range(0, count):
                #Utils.Print("nextIdx: %d, n: %d" % (nextIdx, n))
                nextIdx=(nextIdx + 1)%count
                if not self.nodes[nextIdx].killed:
                    #Utils.Print("nextIdx: %d" % (nextIdx))
                    nextInstanceFound=True
                    break

            if nextInstanceFound is False:
                Utils.Print("ERROR: No active nodes found.")
                return False

            #Utils.Print("nextIdx: %d, count: %d" % (nextIdx, count))
            node=self.nodes[nextIdx]
            if Utils.Debug: Utils.Print("Wait for trasaction id %s on node port %d" % (transId, node.port))
            if node.waitForTransIdOnNode(transId) is False:
                Utils.Print("ERROR: Selected node never received transaction id %s" % (transId))
                return False

            transferAmount -= amount
            transferAmountStr=Node.currencyIntToStr(transferAmount, CORE_SYMBOL)
            fromm=account
            to=accounts[i+1] if i < (count-1) else source
            Utils.Print("Transfer %s units from account %s to %s on  server port %d." %
                    (transferAmountStr, fromm.name, to.name, node.port))

            trans=node.transferFunds(fromm, to, transferAmountStr)
            transId=Node.getTransId(trans)
            if transId is None:
                return False

            if Utils.Debug: Utils.Print("Funds transfered on block num %s." % (transId))

        # As an extra step wait for last transaction on the root node
        node=self.nodes[0]
        if Utils.Debug: Utils.Print("Wait for trasaction id %s on node port %d" % (transId, node.port))
        if node.waitForTransIdOnNode(transId) is False:
            Utils.Print("ERROR: Selected node never received transaction id %s" % (transId))
            return False

        return True

    def validateSpreadFunds(self, initialBalances, transferAmount, source, accounts):
        """Given initial Balances, will validate each account has the expected balance based upon transferAmount.
        This validation is repeated against every node in the cluster."""
        assert(source)
        assert(isinstance(source, Account))
        assert(accounts)
        assert(isinstance(accounts, list))
        assert(len(accounts) > 0)
        assert(initialBalances)
        assert(isinstance(initialBalances, dict))
        assert(isinstance(transferAmount, int))

        for node in self.nodes:
            if node.killed:
                continue

            if Utils.Debug: Utils.Print("Validate funds on %s server port %d." %
                                        (Utils.ServerName, node.port))

            if node.validateFunds(initialBalances, transferAmount, source, accounts) is False:
                Utils.Print("ERROR: Failed to validate funds on  node port: %d" % (node.port))
                return False

        return True

    def spreadFundsAndValidate(self, transferAmount=1):
        """Sprays 'transferAmount' funds across configured accounts and validates action. The spray is done in a trickle down fashion with account 1
        receiving transferAmount*n SYS and forwarding x-transferAmount funds. Transfer actions are spread round-robin across the cluster to vaidate system cohesiveness."""

        if Utils.Debug: Utils.Print("Get initial system balances.")
        initialBalances=self.nodes[0].getBalances([self.defproduceraAccount] + self.accounts)
        assert(initialBalances)
        assert(isinstance(initialBalances, dict))

        if False == self.spreadFunds(self.defproduceraAccount, self.accounts, transferAmount):
            Utils.Print("ERROR: Failed to spread funds across nodes.")
            return False

        Utils.Print("Funds spread across all accounts. Noew validate funds")

        if False == self.validateSpreadFunds(initialBalances, transferAmount, self.defproduceraAccount, self.accounts):
            Utils.Print("ERROR: Failed to validate funds transfer across nodes.")
            return False

        return True

    def validateAccounts(self, accounts, testSysAccounts=True):
        assert(len(self.nodes) > 0)
        node=self.nodes[0]

        myAccounts = []
        if testSysAccounts:
            myAccounts += [self.ioAccount, self.defproduceraAccount, self.defproducerbAccount]
        if accounts:
            assert(isinstance(accounts, list))
            myAccounts += accounts

        node.validateAccounts(myAccounts)

    def createAccountAndVerify(self, account, creator, stakedDeposit=1000):
        """create account, verify account and return transaction id"""
        assert(len(self.nodes) > 0)
        node=self.nodes[0]
        trans=node.createInitializeAccount(account, creator, stakedDeposit)
        assert(trans)
        assert(node.verifyAccount(account))
        return trans

    # # create account, verify account and return transaction id
    # def createAccountAndVerify(self, account, creator, stakedDeposit=1000):
    #     if len(self.nodes) == 0:
    #         Utils.Print("ERROR: No nodes initialized.")
    #         return None
    #     node=self.nodes[0]

    #     transId=node.createAccount(account, creator, stakedDeposit)

    #     if transId is not None and node.verifyAccount(account) is not None:
    #         return transId
    #     return None

    def createInitializeAccount(self, account, creatorAccount, stakedDeposit=1000, waitForTransBlock=False):
        assert(len(self.nodes) > 0)
        node=self.nodes[0]
        trans=node.createInitializeAccount(account, creatorAccount, stakedDeposit, waitForTransBlock)
        return trans

    @staticmethod
    def nodeNameToId(name):
        r"""Convert node name to decimal id. Node name regex is "node_([\d]+)". "node_bios" is a special name which returns -1. Examples: node_00 => 0, node_21 => 21, node_bios => -1. """
        if name == "node_bios":
            return -1

        m=re.search(r"node_([\d]+)", name)
        return int(m.group(1))


    @staticmethod
    def parseProducerKeys(configFile, nodeName):
        """Parse node config file for producer keys. Returns dictionary. (Keys: account name; Values: dictionary objects (Keys: ["name", "node", "private","public"]; Values: account name, node id returned by nodeNameToId(nodeName), private key(string)and public key(string)))."""

        configStr=None
        with open(configFile, 'r') as f:
            configStr=f.read()

        pattern=r"^\s*private-key\s*=\W+(\w+)\W+(\w+)\W+$"
        m=re.search(pattern, configStr, re.MULTILINE)
        if m is None:
            if Utils.Debug: Utils.Print("Failed to find producer keys")
            return None

        pubKey=m.group(1)
        privateKey=m.group(2)

        pattern=r"^\s*producer-name\s*=\W*(\w+)\W*$"
        matches=re.findall(pattern, configStr, re.MULTILINE)
        if matches is None:
            if Utils.Debug: Utils.Print("Failed to find producers.")
            return None

        producerKeys={}
        for m in matches:
            if Utils.Debug: Utils.Print ("Found producer : %s" % (m))
            nodeId=Cluster.nodeNameToId(nodeName)
            keys={"name": m, "node": nodeId, "private": privateKey, "public": pubKey}
            producerKeys[m]=keys

        return producerKeys

    @staticmethod
    def parseClusterKeys(totalNodes):
        """Parse cluster config file. Updates producer keys data members."""

        node="node_bios"
        configFile="etc/io/%s/config.ini" % (node)
        if Utils.Debug: Utils.Print("Parsing config file %s" % configFile)
        producerKeys=Cluster.parseProducerKeys(configFile, node)
        if producerKeys is None:
            Utils.Print("ERROR: Failed to parse io private keys from cluster config files.")
            return None

        for i in range(0, totalNodes):
            node="node_%02d" % (i)
            configFile="etc/io/%s/config.ini" % (node)
            if Utils.Debug: Utils.Print("Parsing config file %s" % configFile)

            keys=Cluster.parseProducerKeys(configFile, node)
            if keys is not None:
                producerKeys.update(keys)

        return producerKeys

    @staticmethod
    def bootstrap(totalNodes, prodCount, biosHost, biosPort, dontKill=False, onlyBios=False):
        """Create 'prodCount' init accounts and deposits 10000000000 SYS in each. If prodCount is -1 will initialize all possible producers.
        Ensure nodes are inter-connected prior to this call. One way to validate this will be to check if every node has block 1."""

        Utils.Print("Starting cluster bootstrap.")
        biosNode=Node(biosHost, biosPort)
        if not biosNode.checkPulse():
            Utils.Print("ERROR: Bios node doesn't appear to be running...")
            return False

        producerKeys=Cluster.parseClusterKeys(totalNodes)
        # should have totalNodes node plus bios node
        if producerKeys is None or len(producerKeys) < (totalNodes+1):
            Utils.Print("ERROR: Failed to parse private keys from cluster config files.")
            return False

        walletMgr=WalletMgr(True)
        walletMgr.killall()
        walletMgr.cleanup()

        if not walletMgr.launch():
            Utils.Print("ERROR: Failed to launch bootstrap wallet.")
            return False
        biosNode.setWalletEndpointArgs(walletMgr.walletEndpointArgs)

        try:
            ignWallet=walletMgr.create("ignition")
            if ignWallet is None:
                Utils.Print("ERROR: Failed to create ignition wallet.")
                return False

            ioName="io"
            ioKeys=producerKeys[ioName]
            ioAccount=Account(ioName)
            ioAccount.ownerPrivateKey=ioKeys["private"]
            ioAccount.ownerPublicKey=ioKeys["public"]
            ioAccount.activePrivateKey=ioKeys["private"]
            ioAccount.activePublicKey=ioKeys["public"]

            if not walletMgr.importKey(ioAccount, ignWallet):
                Utils.Print("ERROR: Failed to import %s account keys into ignition wallet." % (ioName))
                return False

            contract="io.bios"
            contractDir="contracts/%s" % (contract)
            wastFile="contracts/%s/%s.wast" % (contract, contract)
            abiFile="contracts/%s/%s.abi" % (contract, contract)
            Utils.Print("Publish %s contract" % (contract))
            trans=biosNode.publishContract(ioAccount.name, contractDir, wastFile, abiFile, waitForTransBlock=True)
            if trans is None:
                Utils.Print("ERROR: Failed to publish contract %s." % (contract))
                return False

            Node.validateTransaction(trans)

            Utils.Print("Creating accounts: %s " % ", ".join(producerKeys.keys()))
            producerKeys.pop(ioName)
            accounts=[]
            for name, keys in producerKeys.items():
                initx = None
                initx = Account(name)
                initx.ownerPrivateKey=keys["private"]
                initx.ownerPublicKey=keys["public"]
                initx.activePrivateKey=keys["private"]
                initx.activePublicKey=keys["public"]
                trans=biosNode.createAccount(initx, ioAccount, 0)
                if trans is None:
                    Utils.Print("ERROR: Failed to create account %s" % (name))
                    return False
                Node.validateTransaction(trans)
                accounts.append(initx)

            transId=Node.getTransId(trans)
            biosNode.waitForTransIdOnNode(transId)

            Utils.Print("Validating system accounts within bootstrap")
            biosNode.validateAccounts(accounts)

            if not onlyBios:
                if prodCount == -1:
                    setProdsFile="setprods.json"
                    if Utils.Debug: Utils.Print("Reading in setprods file %s." % (setProdsFile))
                    with open(setProdsFile, "r") as f:
                        setProdsStr=f.read()

                        Utils.Print("Setting producers.")
                        opts="--permission io@active"
                        myTrans=biosNode.pushMessage("io", "setprods", setProdsStr, opts)
                        if myTrans is None or not myTrans[0]:
                            Utils.Print("ERROR: Failed to set producers.")
                            return False
                else:
                    counts=dict.fromkeys(range(totalNodes), 0) #initialize node prods count to 0
                    setProdsStr='{"schedule": ['
                    firstTime=True
                    prodNames=[]
                    for name, keys in producerKeys.items():
                        if counts[keys["node"]] >= prodCount:
                            continue
                        if firstTime:
                            firstTime = False
                        else:
                            setProdsStr += ','

                        setProdsStr += ' { "producer_name": "%s", "block_signing_key": "%s" }' % (keys["name"], keys["public"])
                        prodNames.append(keys["name"])
                        counts[keys["node"]] += 1

                    setProdsStr += ' ] }'
                    if Utils.Debug: Utils.Print("setprods: %s" % (setProdsStr))
                    Utils.Print("Setting producers: %s." % (", ".join(prodNames)))
                    opts="--permission io@active"
                    # pylint: disable=redefined-variable-type
                    trans=biosNode.pushMessage("io", "setprods", setProdsStr, opts)
                    if trans is None or not trans[0]:
                        Utils.Print("ERROR: Failed to set producer %s." % (keys["name"]))
                        return False

                trans=trans[1]
                transId=Node.getTransId(trans)
                if not biosNode.waitForTransIdOnNode(transId):
                    return False

                # wait for block production handover (essentially a block produced by anyone but io).
                lam = lambda: biosNode.getInfo()["head_block_producer"] != "io"
                ret=Utils.waitForBool(lam)
                if not ret:
                    Utils.Print("ERROR: Block production handover failed.")
                    return False

            ioTokenAccount=copy.deepcopy(ioAccount)
            ioTokenAccount.name="io.token"
            trans=biosNode.createAccount(ioTokenAccount, ioAccount, 0)
            if trans is None:
                Utils.Print("ERROR: Failed to create account %s" % (ioTokenAccount.name))
                return False

            ioRamAccount=copy.deepcopy(ioAccount)
            ioRamAccount.name="io.ram"
            trans=biosNode.createAccount(ioRamAccount, ioAccount, 0)
            if trans is None:
                Utils.Print("ERROR: Failed to create account %s" % (ioRamAccount.name))
                return False

            ioRamfeeAccount=copy.deepcopy(ioAccount)
            ioRamfeeAccount.name="io.ramfee"
            trans=biosNode.createAccount(ioRamfeeAccount, ioAccount, 0)
            if trans is None:
                Utils.Print("ERROR: Failed to create account %s" % (ioRamfeeAccount.name))
                return False

            ioStakeAccount=copy.deepcopy(ioAccount)
            ioStakeAccount.name="io.stake"
            trans=biosNode.createAccount(ioStakeAccount, ioAccount, 0)
            if trans is None:
                Utils.Print("ERROR: Failed to create account %s" % (ioStakeAccount.name))
                return False

            Node.validateTransaction(trans)
            transId=Node.getTransId(trans)
            biosNode.waitForTransIdOnNode(transId)

            contract="io.token"
            contractDir="contracts/%s" % (contract)
            wastFile="contracts/%s/%s.wast" % (contract, contract)
            abiFile="contracts/%s/%s.abi" % (contract, contract)
            Utils.Print("Publish %s contract" % (contract))
            trans=biosNode.publishContract(ioTokenAccount.name, contractDir, wastFile, abiFile, waitForTransBlock=True)
            if trans is None:
                Utils.Print("ERROR: Failed to publish contract %s." % (contract))
                return False

            # Create currency0000, followed by issue currency0000
            contract=ioTokenAccount.name
            Utils.Print("push create action to %s contract" % (contract))
            action="create"
            data="{\"issuer\":\"%s\",\"maximum_supply\":\"1000000000.0000 %s\",\"can_freeze\":\"0\",\"can_recall\":\"0\",\"can_whitelist\":\"0\"}" % (ioTokenAccount.name, CORE_SYMBOL)
            opts="--permission %s@active" % (contract)
            trans=biosNode.pushMessage(contract, action, data, opts)
            if trans is None or not trans[0]:
                Utils.Print("ERROR: Failed to push create action to io contract.")
                return False

            Node.validateTransaction(trans[1])
            transId=Node.getTransId(trans[1])
            biosNode.waitForTransIdOnNode(transId)

            contract=ioTokenAccount.name
            Utils.Print("push issue action to %s contract" % (contract))
            action="issue"
            data="{\"to\":\"%s\",\"quantity\":\"1000000000.0000 %s\",\"memo\":\"initial issue\"}" % (ioAccount.name, CORE_SYMBOL)
            opts="--permission %s@active" % (contract)
            trans=biosNode.pushMessage(contract, action, data, opts)
            if trans is None or not trans[0]:
                Utils.Print("ERROR: Failed to push issue action to io contract.")
                return False

            Node.validateTransaction(trans[1])
            Utils.Print("Wait for issue action transaction to become finalized.")
            transId=Node.getTransId(trans[1])
            biosNode.waitForTransIdOnNode(transId)

            expectedAmount="1000000000.0000 {0}".format(CORE_SYMBOL)
            Utils.Print("Verify io issue, Expected: %s" % (expectedAmount))
            actualAmount=biosNode.getAccountBalanceStr(ioAccount.name)
            if expectedAmount != actualAmount:
                Utils.Print("ERROR: Issue verification failed. Excepted %s, actual: %s" %
                            (expectedAmount, actualAmount))
                return False

            contract="io.system"
            contractDir="contracts/%s" % (contract)
            wastFile="contracts/%s/%s.wast" % (contract, contract)
            abiFile="contracts/%s/%s.abi" % (contract, contract)
            Utils.Print("Publish %s contract" % (contract))
            trans=biosNode.publishContract(ioAccount.name, contractDir, wastFile, abiFile, waitForTransBlock=True)
            if trans is None:
                Utils.Print("ERROR: Failed to publish contract %s." % (contract))
                return False

            Node.validateTransaction(trans)

            initialFunds="1000000.0000 {0}".format(CORE_SYMBOL)
            Utils.Print("Transfer initial fund %s to individual accounts." % (initialFunds))
            trans=None
            contract=ioTokenAccount.name
            action="transfer"
            for name, keys in producerKeys.items():
                data="{\"from\":\"%s\",\"to\":\"%s\",\"quantity\":\"%s\",\"memo\":\"%s\"}" % (ioAccount.name, name, initialFunds, "init transfer")
                opts="--permission %s@active" % (ioAccount.name)
                trans=biosNode.pushMessage(contract, action, data, opts)
                if trans is None or not trans[0]:
                    Utils.Print("ERROR: Failed to transfer funds from %s to %s." % (ioTokenAccount.name, name))
                    return False

                Node.validateTransaction(trans[1])

            Utils.Print("Wait for last transfer transaction to become finalized.")
            transId=Node.getTransId(trans[1])
            if not biosNode.waitForTransIdOnNode(transId):
                return False

            Utils.Print("Cluster bootstrap done.")
        finally:
            if not dontKill:
                walletMgr.killall()
                walletMgr.cleanup()

        return True


    # Populates list of InstanceInfo objects, matched to actual running instances
    def discoverLocalNodes(self, totalNodes, timeout=0):
        nodes=[]

        pgrepOpts="-fl"
        # pylint: disable=deprecated-method
        if platform.linux_distribution()[0] in ["Ubuntu", "LinuxMint", "Fedora","CentOS Linux","arch"]:
            pgrepOpts="-a"

        cmd="pgrep %s %s" % (pgrepOpts, Utils.ServerName)

        def myFunc():
            psOut=None
            try:
                if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
                psOut=subprocess.check_output(cmd.split()).decode("utf-8")
                return psOut
            except subprocess.CalledProcessError as _:
                pass
            return None

        psOut=Utils.waitForObj(myFunc, timeout)
        if psOut is None:
            Utils.Print("ERROR: No nodes discovered.")
            return nodes

        if Utils.Debug: Utils.Print("pgrep output: \"%s\"" % psOut)
        for i in range(0, totalNodes):
            pattern=r"[\n]?(\d+) (.* --data-dir var/lib/node_%02d)" % (i)
            m=re.search(pattern, psOut, re.MULTILINE)
            if m is None:
                Utils.Print("ERROR: Failed to find %s pid. Pattern %s" % (Utils.ServerName, pattern))
                break
            instance=Node(self.host, self.port + i, pid=int(m.group(1)), cmd=m.group(2), enableMongo=self.enableMongo, mongoHost=self.mongoHost, mongoPort=self.mongoPort, mongoDb=self.mongoDb)
            instance.setWalletEndpointArgs(self.walletEndpointArgs)
            if Utils.Debug: Utils.Print("Node>", instance)
            nodes.append(instance)

        return nodes

    # Kills a percentange of  instances starting from the tail and update InstanceInfos state
    def killSomeInstances(self, killCount, killSignalStr=Utils.SigKillTag):
        killSignal=signal.SIGKILL
        if killSignalStr == Utils.SigTermTag:
            killSignal=signal.SIGTERM
        Utils.Print("Kill %d %s instances with signal %s." % (killCount, Utils.ServerName, killSignal))

        killedCount=0
        for node in reversed(self.nodes):
            if not node.kill(killSignal):
                return False

            killedCount += 1
            if killedCount >= killCount:
                break

        time.sleep(1) # Give processes time to stand down
        return True

    def relaunchInstances(self):

        chainArg=self.__chainSyncStrategy.arg

        for i in range(0, len(self.nodes)):
            node=self.nodes[i]
            if not node.relaunch(i, chainArg):
                return False

        return True

    @staticmethod
    def dumpErrorDetailImpl(fileName):
        Utils.Print("=================================================================")
        Utils.Print("Contents of %s:" % (fileName))
        if os.path.exists(fileName):
            with open(fileName, "r") as f:
                shutil.copyfileobj(f, sys.stdout)
        else:
            Utils.Print("File %s not found." % (fileName))

    def dumpErrorDetails(self):
        fileName="etc/io/node_bios/config.ini"
        Cluster.dumpErrorDetailImpl(fileName)
        fileName="var/lib/node_bios/stderr.txt"
        Cluster.dumpErrorDetailImpl(fileName)

        for i in range(0, len(self.nodes)):
            fileName="etc/io/node_%02d/config.ini" % (i)
            Cluster.dumpErrorDetailImpl(fileName)
            fileName="var/lib/node_%02d/stderr.txt" % (i)
            Cluster.dumpErrorDetailImpl(fileName)

    def killall(self, silent=True):
        cmd="%s -k 15" % (Utils.LauncherPath)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        if 0 != subprocess.call(cmd.split(), stdout=Utils.FNull):
            if not silent: Utils.Print("Launcher failed to shut down  cluster.")

        # ocassionally the launcher cannot kill the  server
        cmd="pkill -9 %s" % (Utils.ServerName)
        if Utils.Debug: Utils.Print("cmd: %s" % (cmd))
        if 0 != subprocess.call(cmd.split(), stdout=Utils.FNull):
            if not silent: Utils.Print("Failed to shut down  cluster.")

        # another explicit nodes shutdown
        for node in self.nodes:
            try:
                if node.pid is not None:
                    os.kill(node.pid, signal.SIGKILL)
            except OSError as _:
                pass

    def isMongodDbRunning(self):
        cmd="%s %s" % (Utils.MongoPath, self.mongoEndpointArgs)
        subcommand="db.version()"
        if Utils.Debug: Utils.Print("echo %s | %s" % (subcommand, cmd))
        ret,outs,errs=Node.stdinAndCheckOutput(cmd.split(), subcommand)
        if ret is not 0:
            Utils.Print("ERROR: Failed to check database version: %s" % (Node.byteArrToStr(errs)) )
            return False
        if Utils.Debug: Utils.Print("MongoDb response: %s" % (outs))
        return True

    def waitForNextBlock(self, timeout=None):
        if timeout is None:
            timeout=Utils.systemWaitTimeout
        node=self.nodes[0]
        return node.waitForNextBlock(timeout)

    def cleanup(self):
        for f in glob.glob("var/lib/node_*"):
            shutil.rmtree(f)
        for f in glob.glob("etc/io/node_*"):
            shutil.rmtree(f)

        if self.enableMongo:
            cmd="%s %s" % (Utils.MongoPath, self.mongoEndpointArgs)
            subcommand="db.dropDatabase()"
            if Utils.Debug: Utils.Print("echo %s | %s" % (subcommand, cmd))
            ret,_,errs=Node.stdinAndCheckOutput(cmd.split(), subcommand)
            if ret is not 0:
                Utils.Print("ERROR: Failed to drop database: %s" % (Node.byteArrToStr(errs)) )


    # Create accounts and validates that the last transaction is received on root node
    def createAccounts(self, creator, waitForTransBlock=True, stakedDeposit=1000):
        if self.accounts is None:
            return True

        transId=None
        for account in self.accounts:
            if Utils.Debug: Utils.Print("Create account %s." % (account.name))
            trans=self.createAccountAndVerify(account, creator, stakedDeposit)
            if trans is None:
                Utils.Print("ERROR: Failed to create account %s." % (account.name))
                return False
            if Utils.Debug: Utils.Print("Account %s created." % (account.name))
            transId=Node.getTransId(trans)

        if waitForTransBlock and transId is not None:
            node=self.nodes[0]
            if Utils.Debug: Utils.Print("Wait for transaction id %s on server port %d." % ( transId, node.port))
            if node.waitForTransIdOnNode(transId) is False:
                Utils.Print("ERROR: Failed waiting for transaction id %s on server port %d." % (
                    transId, node.port))
                return False

        return True
###########################################################################################
