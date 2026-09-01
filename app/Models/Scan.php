<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\SoftDeletes;
use App\Enums\ScanType;
use Illuminate\Support\Facades\Auth;

/**
 * @property int $id 아이디
 * @property ScanType $type 종류
 * @property string $device_type 디바이스 종류
 * @property string $device_uid 디바이스 UID
 * @property int|null $owner_id 소유자 아이디
 * @property int $tester_id 테스터 아이디
 * @property int|null $company_id 기업 아이디
 * @property string|null $scan_vin
 * @property string $car_no 차량번호
 * @property string $car_vin 차대번호
 * @property string|null $car_maker 제조사
 * @property string $car_model 모델명
 * @property string|null $car_submodel 서브모델
 * @property int|null $car_cc 배기량
 * @property int|null $car_year 제조년도
 * @property string|null $car_fuel 연료타입
 * @property string|null $car_battery_capacity 배터리 용량 kWh
 * @property string|null $car_discharge_energy 누적방전전력량
 * @property string|null $car_charge_energy 누적충전전력량
 * @property int|null $car_distance 주행거리 (km)
 * @property array<array-key, mixed>|null $raw 스캔로우데이터 JSON
 * @property array<array-key, mixed>|null $bms_data BMS 데이터
 * @property \Illuminate\Support\Carbon|null $created_at
 * @property \Illuminate\Support\Carbon|null $updated_at
 * @property \Illuminate\Support\Carbon|null $deleted_at
 * @property-read \App\Models\Company|null $company
 * @property-read \App\Models\User|null $owner
 * @property-read \Illuminate\Database\Eloquent\Collection<int, \App\Models\ScanCode> $scanCodes
 * @property-read int|null $scan_codes_count
 * @property-read \App\Models\User $tester
 * @method static \Database\Factories\ScanFactory factory($count = null, $state = [])
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan newModelQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan newQuery()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan onlyTrashed()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan query()
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereCarBatteryCapacity($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereCarCc($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereCarChargeEnergy($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereCarDischargeEnergy($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereCarFuel($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereCarModel($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereCarNo($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereCarVin($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereCarYear($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereCompanyId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereCreatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereDeletedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereDeviceType($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereDeviceUid($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereOwnerId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereRaw($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereScanVin($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereTesterId($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereType($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan whereUpdatedAt($value)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan withTrashed(bool $withTrashed = true)
 * @method static \Illuminate\Database\Eloquent\Builder<static>|Scan withoutTrashed()
 * @mixin \Eloquent
 */
class Scan extends Model
{
    use HasFactory, SoftDeletes;

    protected $fillable = [
        'type',
        'device_type',
        'device_uid',
        'owner_id',
        'tester_id',
        'company_id',
        'scan_vin',
        'car_no',
        'car_vin',
        'car_maker',
        'car_model',
        'car_submodel',
        'car_cc',
        'car_year',
        'car_fuel',
        'car_battery_capacity',
        'car_discharge_energy',
        'car_charge_energy',
        'car_distance',
        'raw',
        'bms_data',
    ];

    protected $casts = [
        'raw' => 'array',
        'bms_data' => 'array',
        'deleted_at' => 'datetime',
        'type' => ScanType::class,
    ];

    /**
     * 사용자 타입에 따른 쿼리 조건 반환
     */
    protected static function getUserTypeQuery($user)
    {
        if (!$user) {
            return null;
        }

        if ($user->type === 'admin') {
            return null;
        }

        if ($user->type === 'owner') {
            return ['owner_id', $user->id];
        }

        if ($user->type === 'tester') {
            return ['tester_id', $user->id];
        }

        return null;
    }

    protected static function booted()
    {
        static::addGlobalScope('user_type_permission', function ($query) {
            $user = Auth::user();
            if (!$user) {
                return;
            }

            if ($user->type === 'admin') {
                return;
            }

            if ($user->type === 'owner') {
                $query->where('owner_id', $user->id);
                return;
            }

            if ($user->type === 'tester') {
                $query->where('tester_id', $user->id);
                return;
            }
        });

        static::creating(function ($scan) {
            $user = Auth::user();
            if (!$user) {
                return;
            }

            if ($user->type === 'owner') {
                // $scan->owner_id = $user->id;
                // $scan->tester_id = null;
                throw new \Exception('오너는 생성할 수 없습니다.', 403);
            }

            if ($user->type === 'tester') {
                $scan->tester_id = $user->id;
                $scan->owner_id = null;
            }
        });

        static::deleting(function ($scan) {
            $user = Auth::user();
            if (!$user) {
                throw new \Exception('권한이 없습니다.', 403);
            }

            if ($user->type !== 'admin' && !($user->type === 'tester' && $scan->tester_id === $user->id)) {
                throw new \Exception('권한이 없습니다.', 403);
            }
        });
    }

    public function owner()
    {
        return $this->belongsTo(User::class, 'owner_id');
    }

    public function tester()
    {
        return $this->belongsTo(User::class, 'tester_id');
    }

    public function company()
    {
        return $this->belongsTo(Company::class);
    }

    public function scanCodes()
    {
        return $this->hasMany(ScanCode::class);
    }

    /**
     * 현재 사용자가 이 스캔에 대한 권한이 있는지 확인
     */
    public function hasPermission(): bool
    {
        $user = Auth::user();
        if (!$user) {
            return false;
        }

        if ($user->type === 'admin') {
            return true;
        }

        if ($user->type === 'owner') {
            return $this->owner_id === $user->id;
        }

        if ($user->type === 'tester') {
            return $this->tester_id === $user->id;
        }

        return false;
    }
}
