<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Support\Facades\Auth;

/**
 * @property int $id
 * @property int|null $user_id 사용자 아이디
 * @property string $ip IP 주소
 * @property string $relation 연관 모델 클래스
 * @property string $relation_type 액션 타입
 * @property int|null $relation_id 연관 모델 아이디
 * @property array<array-key, mixed>|null $changes 변경사항
 * @property string|null $message 추가 메시지
 * @property \Illuminate\Support\Carbon|null $created_at
 * @property \Illuminate\Support\Carbon|null $updated_at
 * @property-read mixed $related_model
 * @property-read \App\Models\User|null $user
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Activity newModelQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Activity newQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Activity query()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Activity whereChanges($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Activity whereCreatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Activity whereId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Activity whereIp($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Activity whereMessage($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Activity whereRelation($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Activity whereRelationId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Activity whereRelationType($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Activity whereUpdatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Activity whereUserId($value)
 * @mixin \Eloquent
 */
class Activity extends Model
{
    protected $fillable = [
        'user_id',
        'ip',
        'relation',
        'relation_type',
        'relation_id',
        'changes',
        'message',
    ];

    protected $casts = [
        'changes' => 'array',
    ];

    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }

    public function getRelatedModelAttribute()
    {
        return $this->relation::find($this->relation_id);
    }

    /**
     * 활동 기록을 쉽게 추가할 수 있는 static 메서드
     *
     * @param Model $model 연관된 모델
     * @param string $type 액션 타입 (예: create, update, delete)
     * @param array|null $changes 변경사항 (기본값: 모델의 변경사항)
     * @param string|null $message 추가 메시지
     * @return Activity
     */
    public static function log(Model $model, string $type, ?array $changes = null, ?string $message = null): Activity
    {
        $changes = $changes ?? $model->getChanges();
        if (empty($changes)) {
            $changes = null;
        }

        return static::create([
            'user_id' => Auth::id(),
            'ip' => request()->ip(),
            'relation' => get_class($model),
            'relation_type' => $type,
            'relation_id' => $model->id ?? null,
            'changes' => $changes,
            'message' => $message,
        ]);
    }
}
