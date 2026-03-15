using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public enum MotionPrimitiveType
{
    Atomic,
    Move,
    Cut
}

public class BasePrimitive
{
    public List<float> parameters;

    public BasePrimitive(List<float> parameters)
    {
        this.parameters = parameters;
    }

    public virtual Vector3 GetPositionAction()
    {
        return new Vector3();
    }

    public virtual Vector3 GetRotationAction()
    {
        return new Vector3(0f, 0f, 0f);
    }

    public virtual float GetGripperAction()
    {
        return 1f;
    }

    public virtual bool CheckComplete(List<float> parameters)
    {
        return true;
    }
}

public class AtomicPrimitive : BasePrimitive
{
    public AtomicPrimitive(List<float> parameters) : base(parameters) {}

    public override Vector3 GetPositionAction()
    {
        return new Vector3(parameters[0], 0f, parameters[1]);
    }

    // Since atomic primitives represent a single action, they are always complete
    public override bool CheckComplete(List<float> parameters)
    {
        return true;
    }
}

public class StraightMovePrimitive : BasePrimitive
{
    public float theta;
    public float distance;
    public uint horizon = 30;
    public Vector3 currentPosition = new Vector3(0f, 0f, 0f);
    public Vector3 targetPosition = new Vector3(0f, 0f, 0f);

    public StraightMovePrimitive(List<float> parameters) : base(parameters)
    {
        theta = ControllerUtils.ConvertRange(
            parameters[0], -1, 1, -Mathf.PI/2, Mathf.PI/2);
        distance = parameters[1];

        targetPosition = new Vector3(
            distance * Mathf.Sin(theta) * horizon,
            0f,
            -distance * Mathf.Cos(theta) * horizon
        );
    }

    public override Vector3 GetPositionAction()
    {
        Vector3 positionDelta = new Vector3(
            distance * Mathf.Sin(theta),
            0f,
            -distance * Mathf.Cos(theta)
        );

        currentPosition += positionDelta;
        return positionDelta;
    }

    public override bool CheckComplete(List<float> parameters)
    {
        return Vector3.Distance(currentPosition, targetPosition) < 0.01f; 
    }
}

public class CutPrimitive : BasePrimitive
{
    public enum State { Move, Close, Open};
    public State state = State.Move;

    public float theta;
    public float distance;
    public uint horizon = 30;
    public Vector3 currentPosition = new Vector3(0f, 0f, 0f);
    public Vector3 targetPosition = new Vector3(0f, 0f, 0f);
    public float desiredGripperPosition = 1f;

    public CutPrimitive(List<float> parameters) : base(parameters)
    {
        theta = ControllerUtils.ConvertRange(
            parameters[0], -1, 1, -Mathf.PI/2, Mathf.PI/2);
        distance = parameters[1];

        targetPosition = new Vector3(
            distance * Mathf.Sin(theta) * horizon,
            0f,
            -distance * Mathf.Cos(theta) * horizon
        );
    }

    public override Vector3 GetPositionAction()
    {
        Vector3 positionDelta = new Vector3(0f, 0f, 0f);
        if (state == State.Move)
        {
            positionDelta = new Vector3(
                distance * Mathf.Sin(theta),
                0f,
                -distance * Mathf.Cos(theta)
            );
        }

        currentPosition += positionDelta;

        return positionDelta;
    }

    public override float GetGripperAction()
    {
        return desiredGripperPosition;
    }

    public override bool CheckComplete(List<float> parameters)
    {
        if (state == State.Move)
        {
            if (Vector3.Distance(currentPosition, targetPosition) < 0.01f)
            {
                state = State.Close;
                desiredGripperPosition = -1f;
            }
        }
        else if (state == State.Close)
        {
            if (parameters[0] < 0.001f)
            {
                state = State.Open;
                desiredGripperPosition = 1f;
            }
        }
        else
        {
            if (parameters[0] > 0.49f)
            {
                return true;
            }
        }
        return false;
    }
}
