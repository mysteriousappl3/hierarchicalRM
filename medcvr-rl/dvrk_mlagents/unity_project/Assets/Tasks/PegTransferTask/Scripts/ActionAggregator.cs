using UnityEngine;
using System.Collections.Generic;
using System.Reflection;
using System;

//public class ActionAggregator : MonoBehaviour
//{
//    // [TODO] -- Drag instance from Unity
//    public DecisionBot decisionBot;

//    // [TODO] -- Drag instance from Unity
//    public ActionStateTransition actionStateTransition;

//    // [TODO] -- Drag instance from Unity
//    public StateDescriptor stateDescriptor;

//    // TODO [Team Discuss] --
//    // 1. Need function to extract only the generated functions if any from plan
//    // 2. How are these rules applied? We need more clarity on this
//    // 3. What will the output of this be? What data type?
//    // 4. Do we keep applying action one after another and use the updated state description as an input for the next action to be applied on this?
//    // 5. Anything else we need?

//    public List<string> futureStateDescriptions;

//    void Start()
//    {
//        futureStateDescriptions = new List<string>();
//    }

//    public void generateFutureStates()
//    {
//        string stateDescription = stateDescriptor.output;

//        if (stateDescription == "")
//        {
//            Debug.Log("[ActionAggregator] -- Please ensure a valid state description is generated before applying action to it");
//            return;
//        }

//        // TODO [Elsie] -- What is the datatype of the transition function collection? Please ensure it makes one defined in ActionStateTransition class.
//        string transitionFunctions = actionStateTransition.output;

//        // TODO: Question 2. from above -- How are these rules applied?

//        // TODO: Write code to populate 'futureStateDescriptions' variable
//    }
//}

public class ActionAggregator : MonoBehaviour
{
    // [TODO] -- Drag instance from Unity
    public DecisionBot decisionBot;

    // [TODO] -- Drag instance from Unity
    public ActionStateTransition actionStateTransition;

    // [TODO] -- Drag instance from Unity
    public StateDescriptor stateDescriptor;

    public List<string> futureStateDescriptions = new List<string>();

    private Assembly _transitionsAssembly;
    private Type _transitionsType;

    public ActionAggregator(string transitionsFile = "ActionStateTransition")
    {
        // Load the assembly containing the action functions
        _transitionsAssembly = Assembly.Load(transitionsFile);
        _transitionsType = _transitionsAssembly.GetType(transitionsFile);
    }

    public Dictionary<string, List<string>> CallFunction(string funcString, Dictionary<string, List<string>> currState)
    {
        // Parse the function string to extract function name and parameters
        var (funcName, parameters) = ParseFunctionString(funcString);

        // Retrieve the function from the module
        MethodInfo method = _transitionsType.GetMethod(funcName);
        if (method == null)
        {
            throw new Exception($"Method {funcName} not found in {_transitionsType.Name}");
        }

        object[] args = new object[parameters.Length + 1];
        args[0] = currState;
        Array.Copy(parameters, 0, args, 1, parameters.Length);

        return (Dictionary<string, List<string>>)method.Invoke(null, args);
    }

    private (string, object[]) ParseFunctionString(string funcString)
    {
        // Example input: "func_name(param1, param2)"
        int openParenIndex = funcString.IndexOf('(');
        int closeParenIndex = funcString.LastIndexOf(')');

        string funcName = funcString.Substring(0, openParenIndex).Trim();
        string paramList = funcString.Substring(openParenIndex + 1, closeParenIndex - openParenIndex - 1);

        string[] paramArray = paramList.Split(',');
        object[] parameters = Array.ConvertAll(paramArray, p => p.Trim().Trim('"'));

        return (funcName, parameters);
    }
}

public static class Executor
{
    public static void Execute()
    {
        var aggregator = new ActionAggregator("StateActionTransitionTest");
        var currState = new Dictionary<string, List<string>>
        {
            { "<peg_red>", new List<string>() },
            { "<peg_green>", new List<string>() },
            { "<peg_blue>", new List<string>() },
            { "<ring_white>", new List<string> { "in(<peg_red>)" } },
            { "<ring_yellow>", new List<string> { "above(<ring_white>)", "in(<peg_red>)" } },
            { "<ring_brown>", new List<string> { "above(<ring_yellow>)", "in(<peg_red>)" } }
        };

        string[] actionSequence = {
            "transfer(\"<peg_red>\", \"<peg_green>\")",
            "transfer(\"<peg_blue>\", \"<peg_red>\")",
            "transfer(\"<peg_green>\", \"<peg_blue>\")",
            "transfer(\"<peg_red>\", \"<peg_green>\")",
            "transfer(\"<peg_blue>\", \"<peg_green>\")"
        };

        foreach (string action in actionSequence)
        {
            currState = aggregator.CallFunction(action, currState);
            Console.WriteLine(PrintState(currState));
        }
    }

    static string PrintState(Dictionary<string, List<string>> state)
    {
        string result = "";
        foreach (var entry in state)
        {
            result += $"{entry.Key}: [{string.Join(", ", entry.Value)}]\n";
        }
        return result;
    }
}
