using UnityEngine;
using System.Collections.Generic;
using System.Collections;
using UnityEngine.Networking;
using System.Linq;

//public class ActionStateTransition : MonoBehaviour
//{
//    // [TODO] Drag instance from Unity
//    public Main main;

//    // TODO: [Elsie & Team Feedback] -- What type should we have the action state transition as? Is this its own class or a dictionary mapping functionName to string definition?
//    // How will this string output we got from the VLM be used?
//    // How will we have a Python function called here? These functions should be in C# language

//    // TODO: [Elsie & Team Feedback] -- Is this output even a string or something else?
//    public string output;

//    public string prompt;

//    private void Start()
//    {
//        output = "";

//        // TODO: [Elsie] -- Please add the prompt for the VLM here
//        prompt = @"";
//    }

//    public void generateTransitionFunctions()
//    {
//        string h1Actions = main.h1Actions;

//        // TODO: OpenAI/Deepseek API call to pass 'prompt' and H1 Actions to the model to generate output and save in 'output' variable
//    }

//}

public class ActionStateTransition : MonoBehaviour
{
    public Main main;
    public StateDescriptor stateDescriptor;
    public H1ActionGenerator h1ActionGenerator;
    public H2ActionGenerator h2ActionGenerator;

    // TODO: [Elsie & Team Feedback] -- Is this output even a string or something else?
    public string output;

    public string prompt;

    private void Start()
    {
        output = "";

        // TODO: [Elsie] -- Please add the prompt for the VLM here
        prompt = @"
            You are an assistant responsible for generating state-action transition function.
            A state is represented in predicates which are shown below. Note that in a state representation,
            [A, B] means A AND B and (A OR B) and NOT A are used to indicate disjunction and negation.
            An example of a state representation is given below. In each key-value pair, the key must be the name of an important object
            in the scene, and the value is a list of spatial properties of the corresponding object.

            Task: Peg Transfer
            Predicates: above(Y), in(X)

            Examples of usage of predicates: ‘in(<peg_1>)’ indicates that the hoop is in peg_1 and ‘above(<hoop_3>)’
            means the hoop is DIRECTLY above hoop_3 and there are no hoops between them.

            For user, they only have to input the definition of the function and a brief description
            eg transfer(X, Y): The ring at the top of pillar X is transferred to pillar Y.


            Now, solve with the following. Please do not wrap the defined functions within a class. Simply give their C# function definitions.
            H1 Actions -- {h1_actions}

            H2 Actions -- {h2_actions}

            State Description -- {state_description}

            Make sure to wrap all the function definitions within a ```start_flag and ```end_flag for parsing purposes.
            Assume the necessary namespaces have already been imported.
            Assume that the H0, H1 and H2 functions have already been defined.
            Only give the function definition without wrapping it inside any class.

            The user instruction will define an action that facilitates the transition from one state to another.
            Your task is to generate a C# function that takes in as the current state and the parameters in the
            action specified by the user as arguments, applies that action to the current state and returns the resulting state.
            "
            ;

    }

    public IEnumerator generateTransitionFunctions()
    {
        string h1Actions = h1ActionGenerator.output;
        string stateDescriptionJSON = stateDescriptor.output;
        string h2Actions = h2ActionGenerator.output;
        // TODO -- Get H2 Actions too

        // TODO -- Replace with proper inputs later
        //string stateDescriptor = @"
        //    {
        //        ""goal_spatial_relations"": {
        //            ""ring_purple"": [""in(peg_red)""],
        //            ""ring_white"": [""in(peg_red)"", ""above(ring_purple)""],
        //            ""ring_yellow"": [""in(peg_red)"", ""above(ring_white)""]  
        //        },
        //        ""constraint_spatial_relations"": {
        //            ""ring_purple"": [
        //                ""NOT(above(ring_purple, ring_white))"",
        //                ""NOT(above(ring_purple, ring_yellow))""
        //            ],
        //            ""ring_white"": [
        //                ""NOT(above(ring_white, ring_yellow))""
        //            ],
        //            ""ring_yellow"": []
        //        }
        //    }";

        h1Actions = @"
            public void MoveHoop(string hoop, string target)
            {
                Move(hoop);
                Grab();
                Move(target);
                Drop();
            }
            ";

        h2Actions = @"
            public void MoveTwoHoops(string hoop1, string hoop2, string targetPeg)
            {
                MoveHoop(hoop1, targetPeg);
                MoveHoop(hoop2, targetPeg);
            }

            public void MoveThreeHoops(string hoop1, string hoop2, string hoop3, string targetPeg)
            {
                MoveHoop(hoop1, targetPeg);
                MoveHoop(hoop2, targetPeg);
                MoveHoop(hoop3, targetPeg);
            }

            public void SwapHoopsBetweenPegs(string hoop1, string peg1, string hoop2, string peg2)
            {
                MoveHoop(hoop1, peg2);
                MoveHoop(hoop2, peg1);
            }
            ";

        prompt = prompt
            .Replace("{h1_actions}", h1Actions.Trim())
            .Replace("{h2_actions}", h2Actions.Trim())
            .Replace("{state_description}", stateDescriptionJSON.Trim());

        //StartCoroutine(CallDeepSeekAPI(prompt));
        yield return StartCoroutine(CallOpenAIAPI(prompt));
    }

    IEnumerator CallOpenAIAPI(string prompt)
    {
        string APIKey = main.getOpenAIAPIKey();
        string APIurl = main.getOpenAIAPIURL();

        // Escape prompt string for JSON
        string escapedPrompt = prompt.Replace("\\", "\\\\")
                                            .Replace("\"", "\\\"")
                                            .Replace("\n", "\\n")
                                            .Replace("\r", "\\r");

        // Build JSON request body
        string jsonRequest = $@"{{
            ""model"": ""o4-mini"",
            ""messages"": [
                {{
                    ""role"": ""system"",
                    ""content"": ""You are an action transition function generator VLM for given user instruction.""
                }},
                {{
                    ""role"": ""user"",
                    ""content"": ""{escapedPrompt}""
                }}
            ],
            ""max_completion_tokens"": 10000
        }}";

        UnityWebRequest request = new UnityWebRequest(APIurl, "POST");
        byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(jsonRequest);
        request.uploadHandler = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();

        request.SetRequestHeader("Content-Type", "application/json");
        request.SetRequestHeader("Authorization", $"Bearer {APIKey}");

        Debug.Log("[ActionTransitionGen] Sending OpenAI API Request...");
        yield return request.SendWebRequest();
        Debug.Log("[ActionTransitionGen] Received API Response.");

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"[ActionTransitionGen] API Request Failed: {request.error}\n{request.downloadHandler.text}");
        }
        else
        {
            string jsonResponse = request.downloadHandler.text;

            OpenAIResponse response = JsonUtility.FromJson<OpenAIResponse>(jsonResponse);

            Debug.Log("[ActionTransitionGen] Raw API response:\n" + jsonResponse);

            if (response.choices != null && response.choices.Length > 0)
            {
                output = response.choices[0].message.content.Trim();
                Debug.Log("[ActionTransitionGen] OpenAI Output:\n" + output);
                output = main.ExtractBetweenFlags(output);
                Debug.Log("EXTRACTED DATA ");
                Debug.Log(output);
            }
            else
            {
                Debug.LogError("[ActionTransitionGen] OpenAI API returned empty choices or malformed response.");
            }
        }
    }

    // Response wrapper for JsonUtility
    [System.Serializable]
    private class OpenAIResponse
    {
        public Choice[] choices;
    }

    [System.Serializable]
    private class Choice
    {
        public Message message;
    }

    [System.Serializable]
    private class Message
    {
        public string role;
        public string content;
    }

    //IEnumerator CallDeepSeekAPI(string promptContent)
    //{
    //    // Escape special characters manually for JSON
    //    string escapedPrompt = promptContent
    //        .Replace("\\", "\\\\")
    //        .Replace("\"", "\\\"")
    //        .Replace("\n", "\\n")
    //        .Replace("\r", "\\r");

    //    string jsonRequest = $@"{{
    //        ""model"": ""deepseek-reasoner"",
    //        ""messages"": [
    //            {{
    //                ""role"": ""user"",
    //                ""content"": ""{escapedPrompt}""
    //            }}
    //        ],
    //        ""temperature"": 0.1,
    //        ""max_tokens"": 1500
    //    }}";

    //    string apiUrl = main.getAPIURL();
    //    string apiKey = main.getAPIKey();

    //    UnityWebRequest request = new UnityWebRequest(apiUrl, "POST");
    //    byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(jsonRequest);
    //    request.uploadHandler = new UploadHandlerRaw(bodyRaw);
    //    request.downloadHandler = new DownloadHandlerBuffer();
    //    request.SetRequestHeader("Content-Type", "application/json");
    //    request.SetRequestHeader("Authorization", "Bearer " + apiKey);

    //    yield return request.SendWebRequest();

    //    if (request.result != UnityWebRequest.Result.Success)
    //    {
    //        Debug.LogError($"API Request Failed: {request.error}\n{request.downloadHandler.text}");
    //    }
    //    else
    //    {
    //        string jsonResponse = request.downloadHandler.text;
    //        DeepSeekResponse response = JsonUtility.FromJson<DeepSeekResponse>(jsonResponse);

    //        if (response.choices != null && response.choices.Length > 0)
    //        {
    //            output = response.choices[0].message.content.Trim();
    //            Debug.Log("<color=magenta>--------- DeepSeek Transition Function Output ---------</color>\n" + output);
    //        }
    //        else
    //        {
    //            Debug.LogError("DeepSeek Reasoner returned empty result or malformed response.");
    //        }
    //    }
    //}

    //[System.Serializable]
    //private class DeepSeekResponse
    //{
    //    public Choice[] choices;
    //}

    //[System.Serializable]
    //private class Choice
    //{
    //    public Message message;
    //}

    //[System.Serializable]
    //private class Message
    //{
    //    public string role;
    //    public string content;
    //}

    // NOTE: Example Transfer function for testing purposes.
    // Ideally what we'll do is make an API call and copy the functions that it gave us. Might be difficult to go from string definitions to actual
    // code copied in but perhaps this is the only manual part we'd have.

    // Example transfer function given by Elsie. Ideally we will be writing the generated result into a file which has the template down and
    // give that to LLM to write to file



    public Dictionary<string, List<string>> MoveHoopTransition(
    Dictionary<string, List<string>> currentState,
    string hoop,
    string targetPeg
)
    {
        // 1. Create a copy of the currentState to modify (so we don't mutate the original directly).
        var newState = currentState.ToDictionary(
            entry => entry.Key,
            entry => entry.Value.ToList()
        );

        // 2. Identify which peg the hoop is currently in (oldPeg).
        string oldPeg = null;
        if (!newState.ContainsKey(hoop))
        {
            // If the hoop doesn't exist in the dictionary, return currentState as is.
            return newState;
        }

        foreach (var predicate in newState[hoop])
        {
            if (predicate.StartsWith("in("))
            {
                // e.g. in(<peg_red>)
                oldPeg = predicate.Substring(
                    predicate.IndexOf("(") + 1,
                    predicate.IndexOf(")") - predicate.IndexOf("(") - 1
                );
                break;
            }
        }

        // 3. Remove "in(<oldPeg>)" from hoop’s predicates and any "above(...)" references for it.
        newState[hoop].RemoveAll(p => p.StartsWith("in(") || p.StartsWith("above("));

        // 4. Remove references from other hoops that say "above(<hoop>)".
        foreach (var obj in newState.Keys)
        {
            newState[obj].RemoveAll(p => p.Contains($"above({hoop})"));
        }

        // 5. Add "in(<targetPeg>)" to the hoop.
        newState[hoop].Add($"in({targetPeg})");

        // 6. Find the top hoop (if any) in targetPeg (the hoop that has "in(targetPeg)" but is
        //    not listed as "above(...)" for any other hoop).
        string topHoopInTarget = null;
        foreach (var obj in newState.Keys)
        {
            if (obj == hoop) continue; // skip the moved hoop itself
            if (newState[obj].Any(p => p == $"in({targetPeg})"))
            {
                // Check if something is "above(obj)". If nothing calls "above(<obj>)", it's top.
                bool isTop = true;
                foreach (var otherObj in newState.Keys)
                {
                    if (newState[otherObj].Any(p => p.Contains($"above({obj})")))
                    {
                        isTop = false;
                        break;
                    }
                }

                if (isTop)
                {
                    topHoopInTarget = obj;
                    break;
                }
            }
        }

        // 7. If there is a top hoop in the target peg, set this hoop to be "above(<thatHoop>)".
        if (topHoopInTarget != null)
        {
            newState[hoop].Add($"above({topHoopInTarget})");
        }

        // 8. If there was an old peg, find the new "top" of that peg and remove "above(...)" from it if referencing the moved hoop.
        //    (We've already removed references to "above(<hoop>)" from all objects, so no further action is required for the old peg's top.)

        return newState;
    }

    public Dictionary<string, List<string>> MoveTwoHoopsTransition(
        Dictionary<string, List<string>> currentState,
        string hoop1,
        string hoop2,
        string targetPeg
    )
    {
        // Move first hoop
        var stateAfterFirstMove = MoveHoopTransition(currentState, hoop1, targetPeg);
        // Move second hoop
        var finalState = MoveHoopTransition(stateAfterFirstMove, hoop2, targetPeg);

        return finalState;
    }

    public Dictionary<string, List<string>> MoveThreeHoopsTransition(
        Dictionary<string, List<string>> currentState,
        string hoop1,
        string hoop2,
        string hoop3,
        string targetPeg
    )
    {
        // Move first hoop
        var stateAfterFirst = MoveHoopTransition(currentState, hoop1, targetPeg);
        // Move second hoop
        var stateAfterSecond = MoveHoopTransition(stateAfterFirst, hoop2, targetPeg);
        // Move third hoop
        var finalState = MoveHoopTransition(stateAfterSecond, hoop3, targetPeg);

        return finalState;
    }

    public Dictionary<string, List<string>> SwapHoopsBetweenPegsTransition(
        Dictionary<string, List<string>> currentState,
        string hoop1,
        string peg1,
        string hoop2,
        string peg2
    )
    {
        // Move hoop1 to peg2
        var stateAfterFirst = MoveHoopTransition(currentState, hoop1, peg2);
        // Move hoop2 to peg1
        var finalState = MoveHoopTransition(stateAfterFirst, hoop2, peg1);

        return finalState;
    }
    
}
