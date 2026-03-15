using System;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

public class RGBDRenderFeature : ScriptableRendererFeature
{
    public class RGBDRenderPass : ScriptableRenderPass
    {
        const string ProfilerTag = "Template Pass";
        RGBDRenderFeature.PassSettings passSettings;

        RenderTargetIdentifier colorBuffer, temporaryBuffer;
        int temporaryBufferID = Shader.PropertyToID("_TemporaryBuffer");

        Material material;

        public RGBDRenderPass(RGBDRenderFeature.PassSettings passSettings)
        {
            this.passSettings = passSettings;
            renderPassEvent = passSettings.renderPassEvent;

            if (material == null) material = CoreUtils.CreateEngineMaterial("Hidden/ColorDepth");
        }

        public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
        {
            // Grab the camera target descriptor. We will use this when creating a temporary render texture.
            RenderTextureDescriptor descriptor = renderingData.cameraData.cameraTargetDescriptor;

            // Set the number of depth bits we need for our temporary render texture.
            descriptor.depthBufferBits = 32;
            descriptor.graphicsFormat = UnityEngine.Experimental.Rendering.GraphicsFormat.R32G32B32A32_SFloat;

            // Enable these if your pass requires access to the CameraDepthTexture or the CameraNormalsTexture.
            ConfigureInput(ScriptableRenderPassInput.Depth);
            // ConfigureInput(ScriptableRenderPassInput.Normal);

            // Grab the color buffer from the renderer camera color target.
            colorBuffer = renderingData.cameraData.renderer.cameraColorTargetHandle;

            // Create a temporary render texture using the descriptor from above.
            cmd.GetTemporaryRT(temporaryBufferID, descriptor, FilterMode.Point);
            temporaryBuffer = new RenderTargetIdentifier(temporaryBufferID);
        }

        public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
        {
            // Grab a command buffer. We put the actual execution of the pass inside of a profiling scope.
            CommandBuffer cmd = CommandBufferPool.Get();
            using (new ProfilingScope(cmd, new ProfilingSampler(ProfilerTag)))
            {
                // Blit from the color buffer to a temporary buffer and back.
                // TODO FIX
                // Blit(cmd, colorBuffer, temporaryBuffer, material);
                // Blit(cmd, temporaryBuffer, colorBuffer);
            }

            // Execute the command buffer and release it.
            context.ExecuteCommandBuffer(cmd);
            CommandBufferPool.Release(cmd);
        }

        public override void OnCameraCleanup(CommandBuffer cmd)
        {
            if (cmd == null) throw new ArgumentNullException("cmd");

            cmd.ReleaseTemporaryRT(temporaryBufferID);
        }
    }

    [System.Serializable]
    public class PassSettings
    {
        public RenderPassEvent renderPassEvent = RenderPassEvent.AfterRenderingTransparents;
    }

    RGBDRenderPass pass;
    public PassSettings passSettings = new();

    public override void Create()
    {
        pass = new RGBDRenderPass(passSettings);
    }

    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        if (renderingData.cameraData.cameraType == CameraType.SceneView) return;
        renderer.EnqueuePass(pass);
    }
}


