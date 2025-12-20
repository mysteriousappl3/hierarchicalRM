using UnityEngine;
using System;
using System.Collections.Generic;
using System.Reflection;

public class InverseActionMapping : MonoBehaviour
{
    private Type actionsType;
    private object actionsInstance;

    public InverseActionMapping(string actionsFile = "ActionDefinitions")
    {
        // Load the type containing the action functions
        actionsType = Type.GetType(actionsFile);
        if (actionsType != null)
        {
            actionsInstance = Activator.CreateInstance(actionsType);
        }
        else
        {
            throw new Exception("Actions class not found.");
        }
    }

    public void ResolveAction(string actionString)
    {
        var (funcName, parameters) = ParseFunctionString(actionString);
        MethodInfo method = actionsType.GetMethod(funcName);
        if (method != null)
        {
            method.Invoke(actionsInstance, parameters);
        }
        else
        {
            throw new Exception($"Method {funcName} not found.");
        }
    }

    private (string, object[]) ParseFunctionString(string funcString)
    {
        // Example input: "MoveHoop(peg_red, peg_green)"
        int openParenIndex = funcString.IndexOf('(');
        string funcName = funcString.Substring(0, openParenIndex).Trim();
        string paramList = funcString.Substring(openParenIndex + 1, funcString.Length - openParenIndex - 2);

        // Convert parameter list to object array
        string[] paramArray = paramList.Split(',');
        object[] parameters = Array.ConvertAll(paramArray, p => p.Trim());

        return (funcName, parameters);
    }
}

// Example usage:
public class InverseMappingExecutor
{
    public static void Execute()
    {
        InverseActionMapping resolver = new InverseActionMapping();
        List<string> actionSequence = new List<string>
        {
            "MoveHoop(peg_red, peg_green)",
            "SwapHoops(peg_red, peg_green, peg_blue)",
            "MoveLowerHoop(peg_red, peg_green, peg_blue)"
        };

        foreach (var action in actionSequence)
        {
            resolver.ResolveAction(action);
        }
    }
}
