using UnityEngine;
using System.Collections.Generic;

namespace Obi
{
    public abstract class ObiClothRendererBase : MonoBehaviour, IActorRenderer, IMeshDataProvider
    {
        public Renderer sourceRenderer { get; protected set; }

        public abstract ObiActor actor { get; }
        public abstract Material[] materials { get; }

        public uint meshInstances { get { return 1; } }

        [field: SerializeField][HideInInspector]
        public Mesh sourceMesh { get; protected set; }

        public virtual int vertexCount { get { return sourceMesh ? sourceMesh.vertexCount : 0; } }
        public virtual int triangleCount { get { return sourceMesh ? sourceMesh.triangles.Length / 3 : 0; } }

        public virtual ObiMesh topology
        {
            get { return ((ObiClothBase)actor).clothBlueprintBase.topology; }
        }

        public abstract ObiSkinMap skinMap
        {
            get; set;
        }

        public virtual bool ValidateRenderer()
        {
            var skm = skinMap;

            bool valid = false;

            if (actor != null && ((ObiClothBase)actor).clothBlueprintBase != null && skm != null)
            {
                // make sure checksums match, the amount of particles and the amount of bind poses in the skinmap match,
                // and the amount of influence counts and vertices also match.
                valid = skm.checksum == ((ObiClothBase)actor).clothBlueprintBase.checksum &&
                        skm.bindPoses.count == actor.particleCount &&
                        skm.particlesOnVertices.influenceOffsets.count == vertexCount + 1;
            }

            if (Application.isPlaying && !valid)
            {
                Debug.LogError("Invalid skinmap in cloth renderer (" + this.name + "). " +
                               "Make sure the skinmap is not null and suitable for the mesh and cloth blueprint being used.");
            }

            return valid;
        }

        public abstract void Bind();

        public virtual void GetVertices(List<Vector3> vertices) { sourceMesh.GetVertices(vertices); }
        public virtual void GetNormals(List<Vector3> normals) { sourceMesh.GetNormals(normals); }
        public virtual void GetTangents(List<Vector4> tangents) { sourceMesh.GetTangents(tangents); }
        public virtual void GetColors(List<Color> colors) { sourceMesh.GetColors(colors); }
        public virtual void GetUVs(int channel, List<Vector2> uvs) { sourceMesh.GetUVs(channel, uvs); }

        public virtual void GetTriangles(List<int> triangles) { triangles.Clear(); triangles.AddRange(sourceMesh.triangles); }
    }
}