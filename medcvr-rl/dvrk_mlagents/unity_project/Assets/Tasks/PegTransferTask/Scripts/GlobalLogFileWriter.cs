using UnityEngine;
using System.IO;

public class GlobalLogFileWriter : MonoBehaviour
{
    StreamWriter writer;

    void Awake()
    {
        // pick the first available filename unity_full_1.log, unity_full_2.log, …
        string dir = Path.Combine(Application.persistentDataPath, "PegTransferTask", "log");
        Directory.CreateDirectory(dir);
        int idx = 0;
        string path;
        do
        {
            string fileName = $"unity_full_{idx}.log";
            path = Path.Combine(dir, fileName);
            Debug.Log(path);
            idx++;
        }
        while (File.Exists(path));

        writer = new StreamWriter(path, true) { AutoFlush = true };
        Application.logMessageReceived += HandleLog;
    
    }

    void HandleLog(string msg, string stack, LogType type)
    {
        writer.WriteLine($"[{System.DateTime.Now:HH:mm:ss}] [{type}] {msg}");
        if (type == LogType.Error || type == LogType.Exception)
            writer.WriteLine(stack);
    }

    void OnDestroy()
    {
        Application.logMessageReceived -= HandleLog;
        writer.Close();
    }
}