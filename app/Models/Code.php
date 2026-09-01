<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\SoftDeletes;

/**
 * @property int $id 아이디
 * @property string $type 차종구분
 * @property string $code 고장코드
 * @property string $unit_name 유니트명
 * @property string|null $unit_type 유니트구분
 * @property string|null $desc 설명
 * @property string|null $detail_desc 상세설명
 * @property string|null $root_cause 주요원인
 * @property string|null $howto_fix1 조치방법1
 * @property string|null $howto_fix2 조치방법2
 * @property string|null $howto_fix3 조치방법3
 * @property \Illuminate\Support\Carbon|null $created_at
 * @property \Illuminate\Support\Carbon|null $updated_at
 * @property \Illuminate\Support\Carbon|null $deleted_at
 * @method static \Database\Factories\CodeFactory factory($count = null, $state = [])
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code newModelQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code newQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code onlyTrashed()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code query()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code whereCode($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code whereCreatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code whereDeletedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code whereDesc($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code whereDetailDesc($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code whereHowtoFix1($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code whereHowtoFix2($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code whereHowtoFix3($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code whereId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code whereRootCause($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code whereType($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code whereUnitName($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code whereUnitType($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code whereUpdatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code withTrashed(bool $withTrashed = true)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Code withoutTrashed()
 * @mixin \Eloquent
 */
class Code extends Model
{
    use HasFactory, SoftDeletes;

    protected $fillable = [
        'type',
        'code',
        'desc',
        'cause',
        'action',
    ];

    protected $casts = [
        'deleted_at' => 'datetime',
    ];
}
