using UnityEngine;
using System.IO;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System;
using UnityEngine.UI;

public class ExecutePlan : MonoBehaviour
{
    public Queue<string> functionQueue = new Queue<string>(); // Queue to hold function calls
    public bool isExecuting = false; // Prevent simultaneous execution

    public LowLevelMotor motor;

    public Button actionExecutor;

    private string logPath = Path.Combine(Application.dataPath, "Tasks/PegTransferTask/executed_functions.txt");

    public void Start()
    {
        // Clear the content if the file exists
        if (File.Exists(logPath))
        {
            File.WriteAllText(logPath, string.Empty);
        }
    }

    public void Execute()
    {

        string filePath = Path.Combine(Application.dataPath, "Tasks/PegTransferTask/plan.txt");
        // string filePath = currentDirectory + "/Assets/Tasks/PegTransferTask/plan.txt";

        UnityEngine.Debug.Log("Path = " + filePath);
        LoadSolutionFromFile(filePath);
        
        UnityEngine.Debug.Log("Plan has been read");

        UnityEngine.Debug.Log("Number of functions to execute in queue = " + functionQueue.Count);

        StartCoroutine(ExecuteSequence());
    }
    public void LoadSolutionFromFile(string filePath)
    {
        if (!File.Exists(filePath))
        {
            UnityEngine.Debug.LogError($"File not found: {filePath}");
            return;
        }

        bool solutionFound = false;
        foreach (string line in File.ReadAllLines(filePath))
        {
            string trimmedLine = line.Trim();
            if (trimmedLine.StartsWith("Solution:")) // Start processing after "Solution:"
            {
                solutionFound = true;
                continue;
            }

            if (solutionFound && IsValidFunction(trimmedLine))
            {
                functionQueue.Enqueue(trimmedLine); // Enqueue valid function calls
            }
        }

        if (functionQueue.Count == 0)
        {
            UnityEngine.Debug.LogError("No valid functions found in the solution.");
            actionExecutor.interactable = false;
        }
        else
        {
            actionExecutor.interactable = true;
        }
    }

    private bool IsValidFunction(string functionCall)
    {
        // Check if the function name matches your known methods
        return functionCall.StartsWith("MoveCoroutine(") ||
               functionCall.StartsWith("GrabCoroutine()") ||
               functionCall.StartsWith("DropCoroutine()");
    }

    public IEnumerator ExecuteNextAction()
    {
        // Make button uninteractable until the function coroutine completes executing
        actionExecutor.interactable = false;

        string functionCall = functionQueue.Dequeue();
        UnityEngine.Debug.Log($"Executing: {functionCall}");

        if (functionCall.StartsWith("MoveCoroutine"))
        {
            // Extract the peg number
            int pegNum = int.Parse(functionCall.Substring(14, 1));
            motor.goalPegNumber = pegNum;
            UnityEngine.Debug.Log("STARTING MOVE COROUTINE!");

            // Append the function to the log file
            AppendActionToLog($"MoveCoroutine({pegNum})");
            yield return StartCoroutine(motor.MoveTerminationCheck());
        }
        else if (functionCall.StartsWith("GrabCoroutine()"))
        {
            UnityEngine.Debug.Log("STARTING GRAB COROUTINE!");

            // Append the function to the log file
            AppendActionToLog($"GrabCoroutine()");
            yield return StartCoroutine(motor.GrabTerminationCheck());
        }
        else if (functionCall.StartsWith("DropCoroutine()"))
        {
            UnityEngine.Debug.Log("STARTING DROP COROUTINE!");

            // Append the function to the log file
            AppendActionToLog($"DropCoroutine()");
            yield return StartCoroutine(motor.DropTerminationCheck());
        }
        else
        {
            UnityEngine.Debug.LogError($"Unknown function call: {functionCall}");
        }

        // Check if the queue is empty
        if (functionQueue.Count != 0)
        {
            // Enable the button
            actionExecutor.interactable = true;
        }
    }

    private void AppendActionToLog(string action)
    {

        // Check if the file exists, and create it if it doesn't
        if (!File.Exists(logPath))
        {
            using (File.Create(logPath)) { } // Create an empty file
        }

        // Write the action to the file, appending a new line
        File.AppendAllText(logPath, $"{action}\n");
    }


    public IEnumerator ExecuteSequence()
    {
        UnityEngine.Debug.Log("Inside Execution function");
        if (isExecuting)
        {
            UnityEngine.Debug.Log("Yielding");
            yield break; // Prevent multiple simultaneous executions
        }
        isExecuting = true;

        UnityEngine.Debug.Log("Attempting to read queue");
        while (functionQueue.Count > 0)
        {
            string functionCall = functionQueue.Dequeue();
            UnityEngine.Debug.Log($"Executing: {functionCall}");

            bool safetyCheckPassed = true;

            if (functionCall.StartsWith("MoveCoroutine"))
            {
                // Extract the peg number
                int pegNum = int.Parse(functionCall.Substring(14, 1));
                motor.goalPegNumber = pegNum;
                UnityEngine.Debug.Log("STARTING MOVE COROUTINE!");
                yield return StartCoroutine(motor.MoveTerminationCheck());
            }
            else if (functionCall.StartsWith("GrabCoroutine()"))
            {
                UnityEngine.Debug.Log("STARTING GRAB COROUTINE!");
                yield return StartCoroutine(motor.GrabTerminationCheck());
            }
            else if (functionCall.StartsWith("DropCoroutine()"))
            {
                UnityEngine.Debug.Log("STARTING DROP COROUTINE!");
                yield return StartCoroutine(motor.DropTerminationCheck());
            }
            else
            {
                UnityEngine.Debug.LogError($"Unknown function call: {functionCall}");
            }

            //// After each function completes, run the safety check
            //safetyCheckPassed = RunSafetyCheck();

            //// If safety check fails, stop the execution
            //if (!safetyCheckPassed)
            //{
            //    UnityEngine.Debug.Log("Sequence execution stopped. Safety violated.");
            //    break;
            //}
        }

        UnityEngine.Debug.Log("Sequence completed successfully.");
        isExecuting = false;
    }

    private bool RunSafetyCheck()
    {
        // Call the Python function to call the safety VLM and determine if agent has violated the plan or not
        string safetyResponse = RunSafetyVLM();

        return safetyResponse.Trim().ToLower() == "true";
    }

    private string RunSafetyVLM()
    {
        // Specify the path to the Python executable in the virtual environment
        string pythonPath = "/Users/aakash/Documents/vlm-peg-transfer/medcvr-rl/dvrk_mlagents/unity_project/Assets/Tasks/PegTransferTask/Python Scripts/venv/bin/python3";

        // Specify the path to your Python script
        string scriptPath = Path.Combine(Application.dataPath, "Tasks/PegTransferTask/Python Scripts/safety-vlm.py");

        // Ensure the script path and Python path are correct
        UnityEngine.Debug.Log("Python Path: " + pythonPath);
        UnityEngine.Debug.Log("Script Path: " + scriptPath);

        // Setup ProcessStartInfo
        ProcessStartInfo start = new ProcessStartInfo();
        start.FileName = pythonPath; // Use the full path to the Python executable
        start.Arguments = $"\"{scriptPath}\""; // Make sure to wrap the script path in quotes to handle spaces
        start.UseShellExecute = false;
        start.RedirectStandardOutput = true;
        start.RedirectStandardError = true; // Capture errors as well

        try
        {
            // Start the process
            using (Process process = Process.Start(start))
            {
                using (StreamReader reader = process.StandardOutput)
                {
                    string result = reader.ReadToEnd();
                    UnityEngine.Debug.Log("Result: " + result);
                }

                // Capture any errors from the Python script
                using (StreamReader errorReader = process.StandardError)
                {
                    string error = errorReader.ReadToEnd();
                    if (!string.IsNullOrEmpty(error))
                    {
                        UnityEngine.Debug.LogError("Error: " + error);
                    }
                }
            }
        }
        catch (Exception ex)
        {
            UnityEngine.Debug.LogError("Exception: " + ex.Message);
        }

        return "";
    }

}
