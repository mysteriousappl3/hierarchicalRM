using UnityEngine;
using System.Collections.Generic;
using System;
using System.Linq;
using System.Text.RegularExpressions;
using System.Collections;

public class Main : MonoBehaviour
{

    public LowLevelMotor motor;
    private string openAIKey = "";
    private const string openAIUrl = "https://api.openai.com/v1/chat/completions";
    private const string openAIReasoningURL = "https://api.openai.com/v1/responses";

    public string userInstruction;
    public string h1Actions;
    public string initialSceneDesc;
    public string initialStateDesc;
    public string envConstraint;
    public string stateDescription;
    public string innerbot_feedback;

    // DecisionBot extracted data
    public List<string> subtaskDescriptions = new List<string>();
    public List<List<string>> subtaskFunctions = new List<List<string>>();
    public List<string> subtaskGoalstates = new List<string>();
    public List<string> allFunctions = new List<string>();
    public StateDescriptor stateDescriptor;

    public Dictionary<string, int> pegColorToNumMapping;  

    public int totalReplanAttempts;
    public int index = 0;   // Index to keep track of Innerbot iterations for subtask checks.

    public int imageCounter = 1;

    // Track the previous state descriptor JSON for use in OuterBot
    public string prevState = "";

    // Stores breakdown of each function type
    public Dictionary<string, List<string>> h1Toh0Mapping = new();
    public Dictionary<string, List<string>> h2Toh1Mapping = new();

    // Stores how many parameters each function expects
    public Dictionary<string, List<string>> functionParamSignature = new();

    // Stores exact call expressions, so you know which args to substitute
    public Dictionary<string, List<string>> functionToCallsWithArgs = new();

    // Only include H1 actions as we consider a transfer to cause state change
    public List<string> h1OnlyFunctionList = new();


    void Start() 
    {
        userInstruction = ""; // Set via UI input field

        initialStateDesc = "";
        initialSceneDesc = "";
        envConstraint = "";
        stateDescription = "";
        innerbot_feedback = "";

        pegColorToNumMapping = new Dictionary<string, int>
        {
            // Naming with just color
            { "green", 1 },
            { "red", 2 },
            { "blue", 3 },
            { "brown", 4 },
            { "orange", 5 }
        };
    }

    public string getOpenAIAPIKey()
    {
        return openAIKey;
    }

    public string getOpenAIReasoningURL()
    {
        return openAIReasoningURL;
    }

    public string getOpenAIAPIURL()
    {
        return openAIUrl;
    }

    ////// FUNCTIONS FOR EXECUTING ROBOT FUNCTIONS FROM H1 AND H2 HIERARCHY METHODS

    // === Entry point to trigger execution ===
    public IEnumerator RunHighLevelFunction(string funcCall)
    {
        ParseFunctionCall(funcCall, out string funcName, out List<string> args);
        yield return StartCoroutine(ExecuteRecursiveCoroutine(funcName, args));
    }

    // === Map pillar names to pillar numbers for execuation ===
    public int MapPillarNameToNum(string pillarName)
    {
        if (pillarName.Contains("peg") || pillarName.Contains("pillar") || pillarName.Contains("rod"))
        {
            foreach (var c in pegColorToNumMapping.Keys)
            {
                if (pillarName.ToLower().Contains(c))
                {
                    return pegColorToNumMapping[c];
                }
            }
            Debug.LogError($"Unknown color in pillar name: {pillarName}");
            return -1;
        } else
        {
            Debug.LogError("Unknown pillar name: " + pillarName);
            return -1; // Invalid pillar number
        }
    }    

    // === Primitive-level coroutine wrapper ===
    public IEnumerator CallPrimitiveAndWait(string funcName, List<string> args)
    {
        // Clean all args in-place from any extra string quotations ' '
        for (int i = 0; i < args.Count; i++)
        {
            args[i] = args[i].Trim('"');
        }

        switch (funcName)
        {
            case "MoveCoroutine":
                yield return motor.MoveCoroutine(MapPillarNameToNum(args[0].ToLower()));
                yield break;
            case "GrabCoroutine":
                yield return motor.GrabCoroutine();
                yield break;
            case "DropCoroutine":
                yield return motor.DropCoroutine();
                yield break;
            default:
                Debug.LogError("Unknown primitive: " + funcName);
                yield break;
        }
    }

    // === Helper: parse "MoveHoop(red, green)" into name + args ===
    public void ParseFunctionCall(string expr, out string funcName, out List<string> args)
    {
        int start = expr.IndexOf('(');
        int end = expr.LastIndexOf(')');

        if (start == -1 || end == -1 || end <= start)
        {
            funcName = expr.Trim();
            args = new List<string>();
            return;
        }

        funcName = expr.Substring(0, start).Trim();
        string argList = expr.Substring(start + 1, end - start - 1);
        args = argList.Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries)
                      .Select(s => s.Trim()).ToList();
    }

    // === Recursive executor that breaks down H2 → H1 → H0 ===
    private IEnumerator ExecuteRecursiveCoroutine(string funcName, List<string> args)
    {
        if (IsPrimitive(funcName))
        {
            yield return CallPrimitiveAndWait(funcName, args);
            yield break;
        }

        if (!functionParamSignature.ContainsKey(funcName) || !functionToCallsWithArgs.ContainsKey(funcName))
        {
            Debug.LogError("Unknown function: " + funcName);
            yield break;
        }

        var paramNames = functionParamSignature[funcName];
        var paramMap = new Dictionary<string, string>();
        for (int i = 0; i < paramNames.Count && i < args.Count; i++)
        {
            string key = ParamNameOnly(paramNames[i]);
            string val = StripQuotes(args[i]);
            paramMap[key] = val;
        }

        foreach (string callExpr in functionToCallsWithArgs[funcName])
        {
            ParseFunctionCall(callExpr, out string subFunc, out List<string> subArgs);
            List<string> resolvedArgs = subArgs.Select(a =>
            {
                string key = CleanPlaceholder(a);
                return paramMap.TryGetValue(key, out var v) ? v : key;
            }).ToList();
            yield return StartCoroutine(ExecuteRecursiveCoroutine(subFunc, resolvedArgs));
        }
    }

    //// Helper Function Definitions/////
    public string ExtractBetweenFlags(string input, string startFlag = "```start_flag", string endFlag = "```end_flag")
    {
        if (string.IsNullOrEmpty(input))
        {
            Debug.LogError("Input to ExtractBetweenFlags is null or empty.");
            return null;
        }

        // strip any backticks
        string cleanStart = startFlag.Trim('`');
        string cleanEnd   = endFlag.Trim('`');

        // split on '_' and build a pattern that allows 0–5 chars between segments
        var startBits = cleanStart.Split('_').Select(Regex.Escape);
        var endBits   = cleanEnd  .Split('_').Select(Regex.Escape);

        string startPattern = string.Join(@".{0,5}", startBits);
        string endPattern   = string.Join(@".{0,5}", endBits);

        // make the backticks around flags optional
        startPattern = $@"(?:```)?{startPattern}(?:```)?";
        endPattern   = $@"(?:```)?{endPattern}(?:```)?";

        // capture everything in between (singleline so '.' matches newlines)
        string pattern = $@"{startPattern}\s*(.*?)\s*{endPattern}";
        var match = Regex.Match(input, pattern, RegexOptions.Singleline);

        if (match.Success)
            return match.Groups[1].Value.Trim();

        Debug.LogError($"Flags not found or in wrong order. Tried pattern: {pattern}");
        return null;
    }

    public Dictionary<string, List<string>> ParseFunctionMappings(string block)
    {
        Dictionary<string, List<string>> mapping = new Dictionary<string, List<string>>();

        // Split by line, not comma
        string[] entries = block.Split(new[] { '\n', '\r' }, System.StringSplitOptions.RemoveEmptyEntries);

        foreach (string rawEntry in entries)
        {
            string entry = rawEntry.Trim();

            if (string.IsNullOrEmpty(entry))
                continue;

            int equalsIndex = entry.IndexOf('=');
            if (equalsIndex == -1)
            {
                Debug.LogError("Invalid format: '=' not found in entry: " + entry);
                continue;
            }

            string key = entry.Substring(0, equalsIndex).Trim();
            string valuePart = entry.Substring(equalsIndex + 1).Trim();

            int openBracket = valuePart.IndexOf('[');
            int closeBracket = valuePart.IndexOf(']');

            if (openBracket == -1 || closeBracket == -1 || closeBracket <= openBracket)
            {
                Debug.LogError("Invalid format: brackets not found or mismatched in entry: " + entry);
                continue;
            }

            string inner = valuePart.Substring(openBracket + 1, closeBracket - openBracket - 1);

            string[] funcs = inner.Split(new[] { ',' }, System.StringSplitOptions.RemoveEmptyEntries);

            List<string> functionList = new List<string>();
            foreach (var f in funcs)
            {
                string cleaned = f.Trim();
                if (!string.IsNullOrEmpty(cleaned))
                    functionList.Add(cleaned);
            }

            mapping[key] = functionList;
        }

        return mapping;
    }

    public void ParseHierarchicalFunctionMappings(string block)
    {
        var h1 = new Dictionary<string, List<string>>();
        var h2 = new Dictionary<string, List<string>>();
        var sigs = new Dictionary<string, List<string>>();
        var calls = new Dictionary<string, List<string>>();

        string[] lines = block.Split(new[] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);

        foreach (string rawLine in lines)
        {
            string line = rawLine.Trim();
            if (string.IsNullOrEmpty(line)) continue;

            int eqIndex = line.IndexOf('=');
            if (eqIndex == -1) continue;

            string header = line.Substring(0, eqIndex).Trim();
            string rhs = line.Substring(eqIndex + 1).Trim();

            // Extract function name and declared parameters
            string funcName;
            List<string> declaredParams = new();
            int parenStart = header.IndexOf('(');
            int parenEnd = header.IndexOf(')');

            if (parenStart != -1 && parenEnd != -1 && parenEnd > parenStart)
            {
                funcName = header.Substring(0, parenStart).Trim();
                string paramBlock = header.Substring(parenStart + 1, parenEnd - parenStart - 1);
                declaredParams = paramBlock.Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries)
                                        .Select(p => p.Trim()).ToList();
            }
            else
            {
                // Handle malformed names like MoveTopObject)
                int trailingParen = header.IndexOf('(');
                funcName = trailingParen != -1
                    ? header.Substring(0, trailingParen).Trim()
                    : header.Trim().TrimEnd(')');
            }

            sigs[funcName] = declaredParams;

            int listStart = rhs.IndexOf('[');
            int listEnd = rhs.IndexOf(']');

            if (listStart == -1 || listEnd == -1 || listEnd <= listStart) continue;

            string callBlock = rhs.Substring(listStart + 1, listEnd - listStart - 1);

            List<string> cleanedNames = new();
            List<string> fullCalls = new();

            // Regex match complete function calls
            var matches = Regex.Matches(callBlock, @"[a-zA-Z_][a-zA-Z0-9_]*\s*\([^\)]*\)");

            foreach (Match match in matches)
            {
                string call = match.Value.Trim();
                fullCalls.Add(call);

                int paren = call.IndexOf('(');
                cleanedNames.Add(paren > 0 ? call.Substring(0, paren).Trim() : call);
            }

            // Store the full call expressions
            calls[funcName] = fullCalls;

            // Classify this function as H1 or H2
            bool allPrimitive = cleanedNames.All(name => IsPrimitive(name));

            if (allPrimitive)
                h1[funcName] = cleanedNames;
            else
                h2[funcName] = cleanedNames;
        }

        // Merge into main mappings
        foreach (var kv in h1) h1Toh0Mapping[kv.Key] = kv.Value;
        foreach (var kv in h2) h2Toh1Mapping[kv.Key] = kv.Value;
        foreach (var kv in sigs) functionParamSignature[kv.Key] = kv.Value;
        foreach (var kv in calls) functionToCallsWithArgs[kv.Key] = kv.Value;
    }



    public bool IsPrimitive(string name)
    {
        return name == "MoveCoroutine" || name == "GrabCoroutine" || name == "DropCoroutine";
    }

    // --- Arg sanitization helpers ---
    static string StripQuotes(string s)
    {
        if (string.IsNullOrEmpty(s)) return s;
        s = s.Trim();
        if (s.Length >= 2 && ((s[0] == '"' && s[^1] == '"') || (s[0] == '\'' && s[^1] == '\'')))
            s = s.Substring(1, s.Length - 2);
        return s.Trim();
    }

    // Converts "string source_peg" -> "source_peg"
    static string ParamNameOnly(string s)
    {
        if (string.IsNullOrEmpty(s)) return s;
        s = s.Trim();
        int lastSpace = s.LastIndexOf(' ');
        if (lastSpace >= 0)
            s = s.Substring(lastSpace + 1);
        return s.Trim();
    }

    // Cleans template args like "source_peg;" -> "source_peg"
    static string CleanPlaceholder(string s)
    {
        if (string.IsNullOrEmpty(s)) return s;
        s = s.Trim();
        s = s.TrimEnd(')', ']', '}', ';', ',');
        return s.Trim();
    }

    // Break down any potential H2 actions into seq of H1 actions.
    public List<List<string>> ExpandToH1Only(List<List<string>> subtaskFunctions)
    {
        List<List<string>> expandedSubtaskFunctions = new();

        foreach (var functionList in subtaskFunctions)
        {
            List<string> expandedFunctions = new();

            foreach (string func in functionList)
            {
                ParseFunctionCall(func, out string funcName, out List<string> args);
                args = args.Select(StripQuotes).ToList();

                if (h2Toh1Mapping.ContainsKey(funcName))
                {
                    if (!functionToCallsWithArgs.ContainsKey(funcName) || !functionParamSignature.ContainsKey(funcName))
                    {
                        Debug.LogError($"Missing function mapping or signature for H2: {funcName}");
                        continue;
                    }

                    var paramNames = functionParamSignature[funcName];
                    var paramMap = new Dictionary<string, string>();
                    for (int i = 0; i < paramNames.Count && i < args.Count; i++)
                    {
                        string key = ParamNameOnly(paramNames[i]);
                        string val = StripQuotes(args[i]);
                        paramMap[key] = val;
                    }

                    foreach (var h1Call in functionToCallsWithArgs[funcName])
                    {
                        ParseFunctionCall(h1Call, out string h1Func, out List<string> h1Args);
                        var resolvedArgs = h1Args.Select(a =>
                        {
                            string key = CleanPlaceholder(a);
                            return paramMap.TryGetValue(key, out var v) ? v : key;
                        }).ToList();
                        expandedFunctions.Add($"{h1Func}({string.Join(", ", resolvedArgs)})");
                    }
                }
                else
                {
                    // Already an H1 function
                    expandedFunctions.Add(func);
                }
            }

            expandedSubtaskFunctions.Add(expandedFunctions);
        }

        return expandedSubtaskFunctions;
    }

    public void ParseDecisionBotOutput(string input, out List<string> subtaskDescriptions, out List<List<string>> subtaskFunctions, out List<string> subtaskGoalstates, out List<string> allFunctions)
    {
        subtaskDescriptions = new List<string>();
        subtaskFunctions = new List<List<string>>();
        subtaskGoalstates = new List<string>();
        allFunctions = new List<string>();

        // Parse number of subtasks (by counting start_subtask_ flags)
        int numSubtasks = 0;
        while (input.Contains($"```start_subtask_{numSubtasks + 1}"))
        {
            numSubtasks++;
        }

        Debug.Log($"Detected {numSubtasks} subtasks.");

        for (int i = 1; i <= numSubtasks; i++)
        {
            // -- extract description
            string subtaskBlock = ExtractBetweenFlags(input, $"```start_subtask_{i}", $"```end_subtask_{i}");
            if (subtaskBlock != null)
            {
                int descEndIdx = subtaskBlock.IndexOf($"```start_subtask_goalstate_{i}");
                string desc = (descEndIdx >= 0) ? subtaskBlock.Substring(0, descEndIdx).Trim() : subtaskBlock.Trim();
                subtaskDescriptions.Add(desc);
            }
            else
            {
                subtaskDescriptions.Add("");
            }

            // -- extract goalstate JSON
            string goalstate = ExtractBetweenFlags(input, $"```start_subtask_goalstate_{i}", $"```end_subtask_goalstate_{i}");
            subtaskGoalstates.Add(goalstate ?? "");

            // -- extract function calls
            string funcBlock = ExtractBetweenFlags(input, $"```start_subtask_funcs_{i}", $"```end_subtask_funcs_{i}");
            if (funcBlock != null)
            {
                // split lines into list, removing empty lines
                var funcs = funcBlock.Split(new[] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries)
                                     .Select(s => s.Trim())
                                     .Where(s => !string.IsNullOrEmpty(s))
                                     .ToList();
                subtaskFunctions.Add(funcs);
            }
            else
            {
                subtaskFunctions.Add(new List<string>());
            }
        }

        // Extract all functions block
        string allFuncBlock = ExtractBetweenFlags(input, "```start_all_functions", "```end_all_functions");
        if (allFuncBlock != null)
        {
            var funcs = allFuncBlock.Split(new[] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries)
                                    .Select(s => s.Trim())
                                    .Where(s => !string.IsNullOrEmpty(s))
                                    .ToList();
            allFunctions = funcs;
        }
    }

    // Function to extract environment spatial relations constraints
    public string ExtractConstraintSpatialRelations(string jsonString)
    {
        string key = "\"constraint_spatial_relations\"";
        int startKeyIndex = jsonString.IndexOf(key);

        if (startKeyIndex == -1)
        {
            Debug.LogError("Key 'constraint_spatial_relations' not found.");
            return null;
        }

        int braceStart = jsonString.IndexOf('{', startKeyIndex);
        if (braceStart == -1)
        {
            Debug.LogError("Opening brace '{' not found after key.");
            return null;
        }

        int braceCount = 1;
        int i = braceStart + 1;

        while (i < jsonString.Length && braceCount > 0)
        {
            if (jsonString[i] == '{')
                braceCount++;
            else if (jsonString[i] == '}')
                braceCount--;
            i++;
        }

        if (braceCount != 0)
        {
            Debug.LogError("Braces not balanced while parsing.");
            return null;
        }

        int braceEnd = i; // i points just after the closing brace
        string extracted = jsonString.Substring(braceStart, braceEnd - braceStart);

        return extracted.Trim();
    }
}
