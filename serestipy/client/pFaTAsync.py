import os
import sys
import time
import json
import errno
import shutil as sh
import serestipy.client.JsonHelper as jh
from serestipy.client.APICommunicator import APICommunicator
import serestipy.client.akcluster 


def rearrange(wholeSettings, newActName, newTaskId, load=""):
    newDict = {}
    task, tasksettings, act, env = jh.dismemberJson(wholeSettings)
    if (list(jh.find("NAME", act))[0] == newActName):
        newDict["TASK"] = task
        newDict["ID"] = newTaskId
        newDict["ACT"] = act
        newDict["ENV"] = env
        newDict["ACT"][list(act.keys())[0]]["LOAD"] = load
        return newDict
    newDict["TASK"] = task
    newDict["TASK_SETTINGS"] = tasksettings
    newDict["ID"] = newTaskId
    newDict["ACT"] = {}
    newDict["ENV"] = {}
    iEnv = 0
    key = list(act.keys())[0]
    for iSys in env.keys():
        sysname = list(jh.find("NAME", env[iSys]))[0]
        if (sysname == newActName):
            newDict["ACT"][str(iSys)] = env[iSys]
            newDict["ACT"][str(iSys)]["LOAD"] = load
        else:
            newDict["ENV"][str(iSys)] = env[iSys]
            newDict["ENV"][str(iSys)]["LOAD"] = load
        iEnv += 1
    newDict["ENV"]["SYS"+str(iEnv+1)] = act[key]
    newDict["ENV"]["SYS"+str(iEnv+1)]["LOAD"] = load
    return newDict.copy()


def bundleResults(tasks):
    name = "LOAD"
    ids = []
    systemnames = []
    for i in range(len(tasks)):
        name += str(tasks[i]["ID"])
        ids.append(str(tasks[i]["ID"]))
        systemnames.append(list(jh.find("NAME", tasks[i]["ACT"]))[0])
    dockerLoadPath = os.path.join("/home/calc", name)
    localLoadPath = os.path.join(os.getenv('DATABASE_DIR'), name)
    if (not os.path.exists(localLoadPath)):
        os.mkdir(localLoadPath)

    def copyanything(src, dst):
        try:
            sh.copytree(src, dst)
        except OSError as exc:
            if exc.errno in (errno.ENOTDIR, errno.EINVAL):
                sh.copy(src, dst)
            else:
                raise
    for i in range(len(systemnames)):
        dst = os.path.join(localLoadPath, systemnames[i])
        src = os.path.join(os.getenv('DATABASE_DIR'), ids[i], systemnames[i])
        copyanything(src, dst)
    return dockerLoadPath


def perform(hosts_list, json_data, nCycles):
    communicator = APICommunicator.getInstance()
    systemnames = list(jh.find("NAME", json_data))
    taskIDs = [i for i in range(len(systemnames))]
    tasks = [rearrange(json_data.copy(), systemnames[i], i, "")
             for i in range(len(systemnames))]
    batchWise = True if (len(systemnames) > len(hosts_list)) else False
    for iCycle in range(nCycles):
        print("o--------------------o")
        print("|       Cycle %2i     |" % (iCycle+1))
        print("o--------------------o")
        if (iCycle > 0):
            start = time.time()
            load = bundleResults(tasks)
            end = time.time()
            print("Time for rearranging directories: ", end - start, "s")
            for i in range(len(taskIDs)):
                taskIDs[i] += len(systemnames)
            tasks = [rearrange(json_data.copy(), systemnames[i],
                               taskIDs[i], load) for i in range(len(systemnames))]
        if (batchWise):
            print(
                "Specified less worker nodes than systems! We will send jobs batch-wise!")
            nBatches = len(systemnames) // len(hosts_list)
            rest = len(systemnames) % len(hosts_list)
            for iBatch in range(0, nBatches * len(hosts_list), len(hosts_list)):
                batchTasks = tasks[iBatch:(iBatch+len(hosts_list))]
                batchIDs = taskIDs[iBatch:(iBatch+len(hosts_list))]
                print("Sending batch with tasks ", batchIDs)
                communicator.requestEvent(
                    "POST", hosts_list, batchIDs, batchTasks)
                communicator.resourcesFinished(hosts_list, batchIDs)
            if (rest > 0):
                end = -1 * rest
                batchTasks = tasks[end:]
                batchIDs = taskIDs[end:]
                print("Sending batch with tasks ", batchIDs)
                communicator.requestEvent(
                    "POST", hosts_list, batchIDs, batchTasks)
                communicator.resourcesFinished(hosts_list, batchIDs)
        else:
            start = time.time()
            communicator.requestEvent("POST", hosts_list, taskIDs, tasks)
            communicator.resourcesFinished(hosts_list, taskIDs)
            end = time.time()
            print("Time taken for cycle: ", end - start, "s")
    # clean-up
    _ = bundleResults(tasks)
    unique_hosts = list(set(hosts_list))
    for i in range(len(unique_hosts)):
        _ = communicator.requestEvent("DELETE", [unique_hosts[i] for j in range(
            len(systemnames) * nCycles)], list(range(len(systemnames) * nCycles)))


if __name__ == "__main__":
    os.environ["DATABASE_DIR"] = "/WORK/p_esch01/scratch_calc/test"
    print("Reading input and preparing calculation...")
    json = jh.input2json(os.path.join(os.getcwd(), sys.argv[1]))
    nSystems = len(list(jh.find("NAME", json)))
    cluster = serestipy.client.akcluster.AKCluster()
    nCPU, nRAM, nNodes, nWorkerPerNode = cluster.determineSettings(nSystems, sys.argv[4], int(sys.argv[2]), int(sys.argv[3]))
    cluster.runInDocker(perform, nCPU, nRAM, nNodes, nWorkerPerNode, sys.argv[4], 4 ,json, int(sys.argv[5]))
