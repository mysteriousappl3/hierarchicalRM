using Unity.MLAgents;
using UnityEngine;

/// <summary>
/// The DecisionRequester component automatically request decisions for an
/// <see cref="Agent"/> instance as soon as the Agent the previous primitive
/// decision has been completed.
/// </summary>
[RequireComponent(typeof(Agent))]
[RequireComponent(typeof(RobotController))]
[DefaultExecutionOrder(-10)]
public class PrimitiveDecisionRequester : MonoBehaviour
{
    [System.NonSerialized]
    Agent m_Agent;
    RobotController m_RobotController;

    public Agent Agent
    {
        get => m_Agent;
    }

    public RobotController RobotController
    {
        get => m_RobotController;
    }

    internal void Awake()
    {
        m_Agent = gameObject.GetComponent<Agent>();
        Debug.Assert(m_Agent != null, "Agent component was not found on this gameObject and is required.");
        m_RobotController = gameObject.GetComponent<RobotController>();
        Debug.Assert(m_RobotController != null, "RobotController component was not found on this gameObject and is required.");
        Debug.Assert(m_RobotController.Controller == RobotController.ControllerType.Primitive, "RobotController component must be of type Primitive.");
        Academy.Instance.AgentPreStep += MakeRequests;
    }

    void OnDestroy()
    {
        if (Academy.IsInitialized)
        {
            Academy.Instance.AgentPreStep -= MakeRequests;
        }
    }

    public struct DecisionRequestContext
    {
        public int AcademyStepCount;
    }

    void MakeRequests(int academyStepCount)
    {
        var context = new DecisionRequestContext
        {
            AcademyStepCount = academyStepCount
        };

        if (ShouldRequestDecision(context))
        {
            m_Agent?.RequestDecision();
        }

        if (ShouldRequestAction(context))
        {
            m_Agent?.RequestAction();
        }
    }

    protected virtual bool ShouldRequestDecision(DecisionRequestContext context)
    {
        return m_RobotController.CheckPrimitiveComplete();
    }

    protected virtual bool ShouldRequestAction(DecisionRequestContext context)
    {
        return true;
    }
}
