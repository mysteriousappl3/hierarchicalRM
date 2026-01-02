using UnityEngine;
using System.Collections.Generic;
using System;
using System.Linq;
using System.Text.RegularExpressions;
using System.Collections;

public class Main : MonoBehaviour
{

    public LowLevelMotor motor; 

    // private const string openAIKey = "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";
    private const string openAIKey = "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";
    private const string openAIUrl = "https://api.openai.com/v1/chat/completions";
    private const string openAIReasoningURL = "https://api.openai.com/v1/responses";

    private const string APIUrl = "https://api.deepseek.com/chat/completions";
    private const string APIKey = "sk-f2310180df084d68b182950773268e77";

    private const string geminiAPIKey = "";
    private const string geminiAPIUrl = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent";

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

    // TODO: Drag Unity Instance
    public StateDescriptor stateDescriptor;
    //public H1ActionGenerator h1actionGenerator;

    public Dictionary<string, int> pegColorToNumMapping;  

    public int totalReplanAttempts; // Allow upto a maximum of 3 total replans before terminating session
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
        userInstruction = "Following tower of hanoi rules, move the hoops to the red peg.";
        // userInstruction = "Transfer all hoops to the red peg such that yellow hoop is on the top and purple hoop is on the bottom. Also, larger hoops should never be above smaller hoops.";
        // userInstruction = "Transfer all hoops to the blue peg such that white hoop is on top and yellow hoop is on the bottom. Make sure the order [white, purple, yellow] is never violated on all pillars except green pillar.";
        // userInstruction = "Transfer all hoops except brown hoop to the blue peg so that purple hoop is still in the bottom and yellow hoop is on top. Also, transfer brown hoop to the red peg. Make sure the order of hoops in the green peg is never violated on all pillars.";
        // userInstruction = "Transfer all hoops on the green peg to the blue peg. For all hoops initially in green peg, make sure no lower hoop is above an upper hoop. Brown and purple hoops should not be above white hoop but white hoop can be above any hoop. White hoop should be in the red peg in goal state but it can be moved around during the task.";
        // userInstruction = "Transfer purple hoop to red peg and yellow hoop to blue peg, and in final state the brown hoop must be above white hoop in the green peg.";
        // userInstruction = "Transfer purple hoop to red peg and yellow hoop to green peg, and in final state the white hoop must be above brown hoop in the blue peg. Make sure a later hoop in the order [yellow, white, brown, purple] is never above an earlier hoop.";

        initialStateDesc = "";

        initialSceneDesc = "";

        // Since all states have same constraints, we will take the env constraint from the initial state

        // old TODO: Remove this commented line later
        // stateDescriptor.generateStateDescription();
        // old TODO: Remove this commented line later
        // string stateDesc = stateDescriptor.output;

        // Done in state desc -- TODO: Add function to parse and extract the env constraints section from the dictionary
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

    public string getAPIKey()
    {
        return APIKey;
    }

    public string getAPIURL()
    {
        return APIUrl;
    }

    public string getGeminiAPIKey()
    {
        return geminiAPIKey;
    }

    public string getGeminiAPIUrl()
    {
        return geminiAPIUrl;
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

        Debug.Log($"Parsed function call: {funcName} with args: {string.Join("; ", args)}");
    }

    // === Recursive executor that breaks down H2 → H1 → H0 ===
    private IEnumerator ExecuteRecursiveCoroutine(string funcName, List<string> args)
    {
        // Debug.Log($"[Exec] ARGS BEING SENT=[{string.Join(", ", args)}]");

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
            Debug.Log("for loop args = " + args[i]);
            paramMap[paramNames[i]] = args[i];
        }
            
        
        // Debug.Log($"[Exec] funcName={funcName} args=[{string.Join(", ", args)}]");
        // Debug.Log($"[Exec] paramNames=[{string.Join(", ", paramNames)}]");
        // Debug.Log($"[Exec] paramMap={string.Join(", ", paramMap.Select(kv => kv.Key + "->" + kv.Value))}");

        foreach (string callExpr in functionToCallsWithArgs[funcName])
        {
            // Debug.Log($"[Exec] template callExpr={callExpr}");
            ParseFunctionCall(callExpr, out string subFunc, out List<string> subArgs);

            // Debug.Log($"[Exec] subFunc={subFunc} subArgs=[{string.Join(", ", subArgs)}]");

            var resolvedArgs = subArgs.Select(arg => paramMap.ContainsKey(arg) ? paramMap[arg] : arg).ToList();
            // Debug.Log($"[Exec] resolvedArgs=[{string.Join(", ", resolvedArgs)}]");
            yield return StartCoroutine(ExecuteRecursiveCoroutine(subFunc, resolvedArgs));
        }
    }
    
    ////////



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

    // Old unused function
    public Dictionary<string, List<string>> ParseFunctionMappings(string block)
    {
        // Debug.Log("AAAA");
        Debug.Log(block);

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
        Debug.Log($"function map = {string.Join(", ", functionToCallsWithArgs.Select(kv => $"{kv.Key}: [{string.Join(", ", kv.Value)}]"))}");
    }



    public bool IsPrimitive(string name)
    {
        return name == "MoveCoroutine" || name == "GrabCoroutine" || name == "DropCoroutine";
    }

    // Break down any potential H2 actions into seq of H1 actions.
public List<List<string>> ExpandToH1Only(List<List<string>> subtaskFunctions)
{
    // --- Helpers ---
    static string StripQuotes(string s)
    {
        if (string.IsNullOrEmpty(s)) return s;
        s = s.Trim();
        if (s.Length >= 2 && ((s[0] == '"' && s[^1] == '"') || (s[0] == '\'' && s[^1] == '\'')))
            s = s.Substring(1, s.Length - 2);
        return s.Trim();
    }

    // Converts "string source_peg" -> "source_peg"
    // Converts "int count" -> "count"
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

    // ----------------
    List<List<string>> expandedSubtaskFunctions = new();

    foreach (var functionList in subtaskFunctions)
    {
        List<string> expandedFunctions = new();

        foreach (string func in functionList)
        {
            Debug.Log("Func call = " + func);

            ParseFunctionCall(func, out string funcName, out List<string> args);
            args = args.Select(StripQuotes).ToList();

            Debug.Log("ARGS = [" + string.Join(", ", args) + "]");

            if (h2Toh1Mapping.ContainsKey(funcName))
            {
                if (!functionToCallsWithArgs.ContainsKey(funcName) || !functionParamSignature.ContainsKey(funcName))
                {
                    Debug.LogError($"Missing function mapping or signature for H2: {funcName}");
                    continue;
                }

                // Build paramMap: placeholderName -> actualArgValue
                var paramNames = functionParamSignature[funcName];
                var paramMap = new Dictionary<string, string>();

                for (int i = 0; i < paramNames.Count && i < args.Count; i++)
                {
                    string key = ParamNameOnly(paramNames[i]);   // FIX: removes "string "
                    string val = StripQuotes(args[i]);           // ensures green_peg not "green_peg"
                    Debug.Log($"BIND {key} -> {val}");
                    paramMap[key] = val;
                }

                foreach (var h1Call in functionToCallsWithArgs[funcName])
                {
                    ParseFunctionCall(h1Call, out string h1Func, out List<string> h1Args);

                    // Resolve placeholders inside H1 templates
                    var resolvedArgs = h1Args.Select(a =>
                    {
                        string key = CleanPlaceholder(a);
                        return paramMap.TryGetValue(key, out var v) ? v : key;
                    }).ToList();

                    Debug.Log($"H1 TEMPLATE: {h1Func}({string.Join(", ", h1Args)})");
                    Debug.Log($"H1 RESOLVED: {h1Func}({string.Join(", ", resolvedArgs)})");

                    expandedFunctions.Add($"{h1Func}({string.Join(", ", resolvedArgs)})");
                }
            }
            else
            {
                Debug.Log("FUNC thats already H1 = " + func);
                expandedFunctions.Add(func);
            }
        }

        expandedSubtaskFunctions.Add(expandedFunctions);
    }

    for (int i = 0; i < expandedSubtaskFunctions.Count; i++)
        Debug.Log($"[H1EXP] Subtask {i + 1}: {string.Join(" | ", expandedSubtaskFunctions[i])}");

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
