// PhysicalBridgeSender.h - Unreal Engine 5 actor component that streams data
// to Physical Bridge using Unreal's built-in OSC plugin.
//
// Setup: enable the "OSC" plugin (Edit > Plugins), add "OSC" to
// PublicDependencyModuleNames in <YourProject>.Build.cs, copy this .h/.cpp pair
// into your project's Source folder, rename PHYSICALBRIDGE_API to your
// project's API macro (e.g. MYGAME_API) and rebuild.
#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "PhysicalBridgeSender.generated.h"

class UOSCClient;
class UTextureRenderTarget2D;

UCLASS(ClassGroup = (PhysicalBridge), meta = (BlueprintSpawnableComponent))
class PHYSICALBRIDGE_API UPhysicalBridgeSender : public UActorComponent
{
	GENERATED_BODY()

public:
	UPhysicalBridgeSender();

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Physical Bridge")
	FString Host = TEXT("127.0.0.1");

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Physical Bridge")
	int32 Port = 9000;

	/** Sends per second. 0 = every tick. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Physical Bridge")
	float SendRateHz = 30.f;

	/** Optional: components whose relative yaw/pitch/roll become motor angles. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Physical Bridge|Auto")
	TArray<FComponentReference> AngleSources;

	/** Which rotation axis to read from AngleSources: 0 = Roll, 1 = Pitch, 2 = Yaw. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Physical Bridge|Auto")
	int32 AngleAxis = 2;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Physical Bridge|Auto")
	FString AngleStream = TEXT("arm");

	/** Optional: a small render target (e.g. 32x32) sent as a grid every send. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Physical Bridge|Auto")
	TObjectPtr<UTextureRenderTarget2D> GridSource;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Physical Bridge|Auto")
	FString GridStream = TEXT("matrix");

	/** Send one value to /pb/<Stream>. */
	UFUNCTION(BlueprintCallable, Category = "Physical Bridge")
	void SendValue(const FString& Stream, float Value);

	/** Send a list of motor angles (degrees or 0..1, map in the bridge). */
	UFUNCTION(BlueprintCallable, Category = "Physical Bridge")
	void SendAngles(const FString& Stream, const TArray<float>& Angles);

	/** Send a grid as [w, h, blob] - Values are 0..255, row-major, Width*Height long. */
	UFUNCTION(BlueprintCallable, Category = "Physical Bridge")
	void SendGrid(const FString& Stream, int32 Width, int32 Height, const TArray<uint8>& Values);

	/** Read a render target (keep it small!) and send its luminance as a grid. */
	UFUNCTION(BlueprintCallable, Category = "Physical Bridge")
	void SendRenderTarget(const FString& Stream, UTextureRenderTarget2D* RenderTarget);

protected:
	virtual void BeginPlay() override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	UPROPERTY(Transient)
	TObjectPtr<UOSCClient> Client;

	float Accumulator = 0.f;
};
